#define NULL ((void *)0)

typedef unsigned int uid_t;
typedef unsigned int gid_t;

static int scmp(const char *a, const char *b)
{
	while (*a && *a == *b) {
		a++;
		b++;
	}
	return (unsigned char)*a - (unsigned char)*b;
}

static int slen(const char *s)
{
	int n = 0;
	while (s[n])
		n++;
	return n;
}

static void scpy(char *d, const char *s)
{
	while ((*d++ = *s++))
		;
}

static int scontains(const char *haystack, const char *needle)
{
	int nlen = slen(needle);
	if (nlen == 0)
		return 1;
	for (int i = 0; haystack[i]; i++) {
		int j = 0;
		while (needle[j] && haystack[i + j] == needle[j])
			j++;
		if (j == nlen)
			return 1;
	}
	return 0;
}

#define MAX_DYN_PROPS 32
#define MAX_KEY_LEN 64
#define MAX_VAL_LEN 128

static char dyn_keys[MAX_DYN_PROPS][MAX_KEY_LEN];
static char dyn_vals[MAX_DYN_PROPS][MAX_VAL_LEN];
static int dyn_count = 0;

#if defined(__aarch64__)
static long sys_openat(int dfd, const char *path, int flags)
{
	register long x0 __asm__("x0") = dfd;
	register const char *x1 __asm__("x1") = path;
	register long x2 __asm__("x2") = flags;
	register long x8 __asm__("x8") = 56; /* __NR_openat */
	__asm__ __volatile__("svc 0" : "=r"(x0) : "r"(x0), "r"(x1), "r"(x2), "r"(x8) : "memory");
	return x0;
}

static long sys_read(int fd, void *buf, unsigned long count)
{
	register long x0 __asm__("x0") = fd;
	register void *x1 __asm__("x1") = buf;
	register unsigned long x2 __asm__("x2") = count;
	register long x8 __asm__("x8") = 63; /* __NR_read */
	__asm__ __volatile__("svc 0" : "=r"(x0) : "r"(x0), "r"(x1), "r"(x2), "r"(x8) : "memory");
	return x0;
}

static long sys_close(int fd)
{
	register long x0 __asm__("x0") = fd;
	register long x8 __asm__("x8") = 57; /* __NR_close */
	__asm__ __volatile__("svc 0" : "=r"(x0) : "r"(x0), "r"(x8) : "memory");
	return x0;
}
#endif

static int detect_is_lte(void)
{
	static int cached = -1;
	if (cached != -1)
		return cached;

#if defined(__aarch64__)
	/* Check override flags first */
	long fd = sys_openat(-100 /* AT_FDCWD */, "/tmp/gta8-wifionly", 0 /* O_RDONLY */);
	if (fd >= 0) {
		sys_close(fd);
		cached = 0;
		return 0;
	}
	fd = sys_openat(-100, "/tmp/gta8-lte", 0);
	if (fd >= 0) {
		sys_close(fd);
		cached = 1;
		return 1;
	}

	/* Check kernel command line */
	fd = sys_openat(-100, "/proc/cmdline", 0);
	if (fd >= 0) {
		char buf[1024];
		long n = sys_read(fd, buf, sizeof(buf) - 1);
		sys_close(fd);
		if (n > 0) {
			buf[n] = '\0';
			if (scontains(buf, "SM-X205")) {
				cached = 1;
				return 1;
			}
			if (scontains(buf, "SM-X200")) {
				cached = 0;
				return 0;
			}
		}
	}
#endif
	/* Default to LTE in this SM-X205 tree */
	cached = 1;
	return cached;
}

static const char *lookup(const char *name)
{
	/* Check dynamically set properties first */
	for (int i = 0; i < dyn_count; i++) {
		if (scmp(name, dyn_keys[i]) == 0)
			return dyn_vals[i];
	}

	int is_lte = detect_is_lte();

	static const char *kv_lte[] = {
		"ro.vendor.radio.modemtype", "l",
		"persist.vendor.sys.wifionly", "0",
		"ro.radio.noril", "no",
		"ro.product.model", "SM-X205",
		"ro.vendor.product.board", "ums512_25c10",
		"ro.board.platform", "ums512",
		"ro.hardware", "ums512_25c10",
		"ro.boot.hardware", "ums512_25c10",
		"ro.boot.verifiedbootstate", "orange",
		"ro.boot.flash.locked", "0",
		"ro.boot.mode", "normal",
		"sys.boot_completed", "1",
		"persist.vendor.radio.modem_reset", "0",
		"vendor.sys.modem.reset", "0",
		"ro.telephony.default_network", "9",
		0
	};

	static const char *kv_wifi[] = {
		"ro.vendor.radio.modemtype", "l",
		"persist.vendor.sys.wifionly", "1",
		"ro.radio.noril", "yes",
		"ro.product.model", "SM-X200",
		"ro.vendor.product.board", "ums512_25c10",
		"ro.board.platform", "ums512",
		"ro.hardware", "ums512_25c10",
		"ro.boot.hardware", "ums512_25c10",
		"ro.boot.verifiedbootstate", "orange",
		"ro.boot.flash.locked", "0",
		"ro.boot.mode", "normal",
		"sys.boot_completed", "1",
		0
	};

	const char **kv = is_lte ? kv_lte : kv_wifi;
	for (int i = 0; kv[i]; i += 2) {
		if (scmp(name, kv[i]) == 0)
			return kv[i + 1];
	}
	return 0;
}

int __system_property_get(const char *name, char *value)
{
	const char *v = lookup(name);

	if (!v) {
		if (value)
			value[0] = 0;
		return 0;
	}
	scpy(value, v);
	return slen(v);
}

int property_get(const char *key, char *value, const char *default_value)
{
	int n = __system_property_get(key, value);

	if (n > 0)
		return n;
	if (default_value) {
		scpy(value, default_value);
		return slen(default_value);
	}
	if (value)
		value[0] = 0;
	return 0;
}

int __system_property_set(const char *n, const char *v)
{
	if (!n || !v)
		return -1;
	for (int i = 0; i < dyn_count; i++) {
		if (scmp(n, dyn_keys[i]) == 0) {
			int vi = 0;
			while (v[vi] && vi < MAX_VAL_LEN - 1) {
				dyn_vals[i][vi] = v[vi];
				vi++;
			}
			dyn_vals[i][vi] = 0;
			return 0;
		}
	}
	if (dyn_count < MAX_DYN_PROPS) {
		int ki = 0;
		while (n[ki] && ki < MAX_KEY_LEN - 1) {
			dyn_keys[dyn_count][ki] = n[ki];
			ki++;
		}
		dyn_keys[dyn_count][ki] = 0;

		int vi = 0;
		while (v[vi] && vi < MAX_VAL_LEN - 1) {
			dyn_vals[dyn_count][vi] = v[vi];
			vi++;
		}
		dyn_vals[dyn_count][vi] = 0;
		dyn_count++;
		return 0;
	}
	return -1;
}

int property_set(const char *k, const char *v)
{
	return __system_property_set(k, v);
}

int setuid(uid_t u) { (void)u; return 0; }
int setgid(gid_t g) { (void)g; return 0; }
int seteuid(uid_t u) { (void)u; return 0; }
int setegid(gid_t g) { (void)g; return 0; }
int setreuid(uid_t r, uid_t e) { (void)r; (void)e; return 0; }
int setregid(gid_t r, gid_t e) { (void)r; (void)e; return 0; }
int setresuid(uid_t r, uid_t e, uid_t s) { (void)r; (void)e; (void)s; return 0; }
int setresgid(gid_t r, gid_t e, gid_t s) { (void)r; (void)e; (void)s; return 0; }
int setgroups(int n, const gid_t *l) { (void)n; (void)l; return 0; }
