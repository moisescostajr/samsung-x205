/*
 * Minimal DMA-BUF heaps ("dma_heap") for the 4.14 gta8wifi kernel.
 *
 * The Mali r24p0 userspace allocates every buffer through the dma_heap
 * devices, which Linux only gained in 5.6. Without them libmali's GBM and its
 * Wayland client EGL fail immediately:
 *
 *   openat("/dev/dma_heap/system-uncached", O_RDWR) = -1 ENOENT
 *   openat("/dev/dma_heap/system", O_RDWR)          = -1 ENOENT
 *
 * This provides the "system" and "system-uncached" heaps with the upstream
 * ioctl ABI, backed by plain pages exported as a dma_buf, so the blob can
 * allocate without a render node (sprd is display-only).
 *
 * Only what the blob needs is implemented: allocate, map for a device,
 * mmap, vmap and CPU-access bracketing.
 */
#include <linux/cdev.h>
#include <linux/device.h>
#include <linux/dma-buf.h>
#include <linux/dma-mapping.h>
#include <linux/err.h>
#include <linux/fs.h>
#include <linux/highmem.h>
#include <linux/module.h>
#include <linux/scatterlist.h>
#include <linux/slab.h>
#include <linux/uaccess.h>
#include <linux/vmalloc.h>

#define DEVNAME "dma_heap"

/* uapi/linux/dma-heap.h */
struct dma_heap_allocation_data {
	__u64 len;
	__u32 fd;
	__u32 fd_flags;
	__u64 heap_flags;
};

#define DMA_HEAP_IOC_MAGIC 'H'
#define DMA_HEAP_IOCTL_ALLOC \
	_IOWR(DMA_HEAP_IOC_MAGIC, 0x0, struct dma_heap_allocation_data)

/* Same order ladder the upstream system heap uses. */
static const unsigned int orders[] = { 8, 4, 0 };

struct heap_buffer {
	struct sg_table sgt;
	struct page **pages;
	unsigned int nr_pages;
	size_t len;
	bool uncached;
	void *vaddr;
	struct mutex lock;
};

struct heap_attachment {
	struct sg_table *table;
	struct device *dev;
	struct list_head list;
};

static void heap_buffer_free(struct heap_buffer *buf)
{
	struct scatterlist *sg;
	unsigned int i;

	if (buf->vaddr)
		vunmap(buf->vaddr);

	for_each_sg(buf->sgt.sgl, sg, buf->sgt.orig_nents, i)
		__free_pages(sg_page(sg), get_order(sg->length));

	sg_free_table(&buf->sgt);
	kvfree(buf->pages);
	kfree(buf);
}

static struct sg_table *dup_sg_table(struct sg_table *table)
{
	struct sg_table *new_table;
	struct scatterlist *sg, *new_sg;
	unsigned int i;
	int ret;

	new_table = kzalloc(sizeof(*new_table), GFP_KERNEL);
	if (!new_table)
		return ERR_PTR(-ENOMEM);

	ret = sg_alloc_table(new_table, table->orig_nents, GFP_KERNEL);
	if (ret) {
		kfree(new_table);
		return ERR_PTR(-ENOMEM);
	}

	new_sg = new_table->sgl;
	for_each_sg(table->sgl, sg, table->orig_nents, i) {
		sg_set_page(new_sg, sg_page(sg), sg->length, sg->offset);
		new_sg = sg_next(new_sg);
	}

	return new_table;
}

static int heap_attach(struct dma_buf *dmabuf, struct device *dev,
		       struct dma_buf_attachment *attachment)
{
	struct heap_buffer *buf = dmabuf->priv;
	struct heap_attachment *a;
	struct sg_table *table;

	a = kzalloc(sizeof(*a), GFP_KERNEL);
	if (!a)
		return -ENOMEM;

	table = dup_sg_table(&buf->sgt);
	if (IS_ERR(table)) {
		kfree(a);
		return PTR_ERR(table);
	}

	a->table = table;
	a->dev = dev;
	attachment->priv = a;

	return 0;
}

static void heap_detach(struct dma_buf *dmabuf,
			struct dma_buf_attachment *attachment)
{
	struct heap_attachment *a = attachment->priv;

	if (!a)
		return;

	sg_free_table(a->table);
	kfree(a->table);
	kfree(a);
	attachment->priv = NULL;
}

static struct sg_table *heap_map_dma_buf(struct dma_buf_attachment *attachment,
					 enum dma_data_direction direction)
{
	struct heap_attachment *a = attachment->priv;
	struct sg_table *table = a->table;

	if (!dma_map_sg(attachment->dev, table->sgl, table->orig_nents,
			direction))
		return ERR_PTR(-ENOMEM);

	table->nents = table->orig_nents;

	return table;
}

static void heap_unmap_dma_buf(struct dma_buf_attachment *attachment,
			       struct sg_table *table,
			       enum dma_data_direction direction)
{
	dma_unmap_sg(attachment->dev, table->sgl, table->orig_nents, direction);
}

static int heap_mmap(struct dma_buf *dmabuf, struct vm_area_struct *vma)
{
	struct heap_buffer *buf = dmabuf->priv;
	unsigned long addr = vma->vm_start;
	struct scatterlist *sg;
	unsigned int i;
	int ret;

	if (buf->uncached)
		vma->vm_page_prot = pgprot_writecombine(vma->vm_page_prot);

	for_each_sg(buf->sgt.sgl, sg, buf->sgt.orig_nents, i) {
		struct page *page = sg_page(sg);
		unsigned long remainder = vma->vm_end - addr;
		unsigned long len = min_t(unsigned long, sg->length, remainder);

		if (!len)
			break;

		ret = remap_pfn_range(vma, addr, page_to_pfn(page), len,
				      vma->vm_page_prot);
		if (ret)
			return ret;

		addr += len;
	}

	return 0;
}

static void *heap_vmap(struct dma_buf *dmabuf)
{
	struct heap_buffer *buf = dmabuf->priv;
	pgprot_t prot = buf->uncached ? pgprot_writecombine(PAGE_KERNEL)
				      : PAGE_KERNEL;

	mutex_lock(&buf->lock);
	if (!buf->vaddr)
		buf->vaddr = vmap(buf->pages, buf->nr_pages, VM_MAP, prot);
	mutex_unlock(&buf->lock);

	return buf->vaddr;
}

static void heap_vunmap(struct dma_buf *dmabuf, void *vaddr)
{
	/* Kept until release; repeated vmap of the same buffer is common. */
}

static void *heap_kmap(struct dma_buf *dmabuf, unsigned long offset)
{
	struct heap_buffer *buf = dmabuf->priv;

	if (offset >= buf->nr_pages)
		return NULL;

	return kmap(buf->pages[offset]);
}

static void heap_kunmap(struct dma_buf *dmabuf, unsigned long offset, void *ptr)
{
	struct heap_buffer *buf = dmabuf->priv;

	if (offset < buf->nr_pages)
		kunmap(buf->pages[offset]);
}

static void *heap_kmap_atomic(struct dma_buf *dmabuf, unsigned long offset)
{
	struct heap_buffer *buf = dmabuf->priv;

	if (offset >= buf->nr_pages)
		return NULL;

	return kmap_atomic(buf->pages[offset]);
}

static void heap_kunmap_atomic(struct dma_buf *dmabuf, unsigned long offset,
			       void *ptr)
{
	kunmap_atomic(ptr);
}

static int heap_begin_cpu_access(struct dma_buf *dmabuf,
				 enum dma_data_direction direction)
{
	return 0;
}

static int heap_end_cpu_access(struct dma_buf *dmabuf,
			       enum dma_data_direction direction)
{
	return 0;
}

static void heap_dma_buf_release(struct dma_buf *dmabuf)
{
	heap_buffer_free(dmabuf->priv);
}

static const struct dma_buf_ops heap_buf_ops = {
	.attach = heap_attach,
	.detach = heap_detach,
	.map_dma_buf = heap_map_dma_buf,
	.unmap_dma_buf = heap_unmap_dma_buf,
	.release = heap_dma_buf_release,
	.begin_cpu_access = heap_begin_cpu_access,
	.end_cpu_access = heap_end_cpu_access,
	.map_atomic = heap_kmap_atomic,
	.unmap_atomic = heap_kunmap_atomic,
	.map = heap_kmap,
	.unmap = heap_kunmap,
	.mmap = heap_mmap,
	.vmap = heap_vmap,
	.vunmap = heap_vunmap,
};

static struct page *alloc_largest(unsigned long size, unsigned int *order_out)
{
	unsigned int i;

	for (i = 0; i < ARRAY_SIZE(orders); i++) {
		unsigned long chunk = PAGE_SIZE << orders[i];
		struct page *page;
		gfp_t gfp = GFP_KERNEL | __GFP_ZERO;

		if (size < chunk)
			continue;

		if (orders[i] > 0)
			gfp |= __GFP_NORETRY | __GFP_NOWARN | __GFP_COMP;

		page = alloc_pages(gfp, orders[i]);
		if (!page)
			continue;

		*order_out = orders[i];
		return page;
	}

	return NULL;
}

static int heap_allocate(size_t len, bool uncached, unsigned int fd_flags)
{
	struct heap_buffer *buf;
	struct scatterlist *sg;
	struct list_head pages;
	struct page *page, *tmp;
	unsigned long remaining;
	unsigned int nr_chunks = 0, i, p = 0;
	DEFINE_DMA_BUF_EXPORT_INFO(exp_info);
	struct dma_buf *dmabuf;
	int ret;

	len = PAGE_ALIGN(len);
	if (!len)
		return -EINVAL;

	buf = kzalloc(sizeof(*buf), GFP_KERNEL);
	if (!buf)
		return -ENOMEM;

	mutex_init(&buf->lock);
	buf->len = len;
	buf->uncached = uncached;
	INIT_LIST_HEAD(&pages);

	remaining = len;
	while (remaining) {
		unsigned int order = 0;

		page = alloc_largest(remaining, &order);
		if (!page) {
			ret = -ENOMEM;
			goto err_pages;
		}
		list_add_tail(&page->lru, &pages);
		remaining -= min_t(unsigned long, remaining,
				   PAGE_SIZE << order);
		nr_chunks++;
	}

	ret = sg_alloc_table(&buf->sgt, nr_chunks, GFP_KERNEL);
	if (ret)
		goto err_pages;

	buf->nr_pages = len / PAGE_SIZE;
	buf->pages = kvmalloc_array(buf->nr_pages, sizeof(*buf->pages),
				    GFP_KERNEL);
	if (!buf->pages) {
		ret = -ENOMEM;
		goto err_table;
	}

	sg = buf->sgt.sgl;
	list_for_each_entry_safe(page, tmp, &pages, lru) {
		unsigned int order = compound_order(page);
		unsigned int chunk = PAGE_SIZE << order;

		sg_set_page(sg, page, chunk, 0);
		sg = sg_next(sg);
		list_del(&page->lru);

		for (i = 0; i < (1u << order) && p < buf->nr_pages; i++)
			buf->pages[p++] = page + i;
	}

	exp_info.ops = &heap_buf_ops;
	exp_info.size = len;
	exp_info.flags = fd_flags & (O_CLOEXEC | O_ACCMODE);
	exp_info.priv = buf;

	dmabuf = dma_buf_export(&exp_info);
	if (IS_ERR(dmabuf)) {
		ret = PTR_ERR(dmabuf);
		goto err_table;
	}

	ret = dma_buf_fd(dmabuf, fd_flags & O_CLOEXEC);
	if (ret < 0) {
		dma_buf_put(dmabuf);
		return ret;
	}

	return ret;

err_table:
	kvfree(buf->pages);
	sg_free_table(&buf->sgt);
err_pages:
	list_for_each_entry_safe(page, tmp, &pages, lru) {
		list_del(&page->lru);
		__free_pages(page, compound_order(page));
	}
	kfree(buf);

	return ret;
}

struct heap_device {
	struct cdev cdev;
	struct device *dev;
	bool uncached;
	const char *name;
};

#define MAX_HEAPS 2
static struct heap_device heaps[MAX_HEAPS];
static struct class *heap_class;
static dev_t heap_devt;

static int heap_open(struct inode *inode, struct file *file)
{
	file->private_data = container_of(inode->i_cdev, struct heap_device,
					  cdev);

	return 0;
}

static long heap_ioctl(struct file *file, unsigned int cmd, unsigned long arg)
{
	struct heap_device *heap = file->private_data;
	struct dma_heap_allocation_data data;
	int fd;

	if (cmd != DMA_HEAP_IOCTL_ALLOC)
		return -ENOTTY;

	if (copy_from_user(&data, (void __user *)arg, sizeof(data)))
		return -EFAULT;

	if (data.fd_flags & ~(O_CLOEXEC | O_ACCMODE))
		return -EINVAL;
	if (data.heap_flags)
		return -EINVAL;

	fd = heap_allocate(data.len, heap->uncached, data.fd_flags);
	if (fd < 0)
		return fd;

	data.fd = fd;
	if (copy_to_user((void __user *)arg, &data, sizeof(data))) {
		/* Userspace never saw the fd; drop it. */
		return -EFAULT;
	}

	return 0;
}

static const struct file_operations heap_fops = {
	.owner = THIS_MODULE,
	.open = heap_open,
	.unlocked_ioctl = heap_ioctl,
	.compat_ioctl = heap_ioctl,
};

static char *heap_devnode(struct device *dev, umode_t *mode)
{
	if (mode)
		*mode = 0666;

	return kasprintf(GFP_KERNEL, "dma_heap/%s", dev_name(dev));
}

static int add_heap(int index, const char *name, bool uncached)
{
	struct heap_device *heap = &heaps[index];
	dev_t devt = MKDEV(MAJOR(heap_devt), index);
	int ret;

	heap->uncached = uncached;
	heap->name = name;

	cdev_init(&heap->cdev, &heap_fops);
	heap->cdev.owner = THIS_MODULE;
	ret = cdev_add(&heap->cdev, devt, 1);
	if (ret)
		return ret;

	heap->dev = device_create(heap_class, NULL, devt, NULL, "%s", name);
	if (IS_ERR(heap->dev)) {
		cdev_del(&heap->cdev);
		return PTR_ERR(heap->dev);
	}

	return 0;
}

static int __init dma_heap_compat_init(void)
{
	int ret;

	ret = alloc_chrdev_region(&heap_devt, 0, MAX_HEAPS, DEVNAME);
	if (ret)
		return ret;

	heap_class = class_create(THIS_MODULE, DEVNAME);
	if (IS_ERR(heap_class)) {
		ret = PTR_ERR(heap_class);
		goto err_chrdev;
	}
	heap_class->devnode = heap_devnode;

	ret = add_heap(0, "system", false);
	if (ret)
		goto err_class;

	ret = add_heap(1, "system-uncached", true);
	if (ret)
		goto err_heap0;

	pr_info("dma_heap_compat: /dev/dma_heap/{system,system-uncached} ready\n");

	return 0;

err_heap0:
	device_destroy(heap_class, MKDEV(MAJOR(heap_devt), 0));
	cdev_del(&heaps[0].cdev);
err_class:
	class_destroy(heap_class);
err_chrdev:
	unregister_chrdev_region(heap_devt, MAX_HEAPS);

	return ret;
}

static void __exit dma_heap_compat_exit(void)
{
	int i;

	for (i = 0; i < MAX_HEAPS; i++) {
		device_destroy(heap_class, MKDEV(MAJOR(heap_devt), i));
		cdev_del(&heaps[i].cdev);
	}
	class_destroy(heap_class);
	unregister_chrdev_region(heap_devt, MAX_HEAPS);
}

module_init(dma_heap_compat_init);
module_exit(dma_heap_compat_exit);
MODULE_LICENSE("GPL v2");
MODULE_DESCRIPTION("DMA-BUF system heaps for 4.14, for the Mali r24p0 blob");
