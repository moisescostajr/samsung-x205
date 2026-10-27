<?php
$streams = [];
if (is_file(__DIR__.'/config.php')) {
    $streams = (require __DIR__.'/config.php')['iptv'] ?? [];
}
$src = $streams[$_GET['id'] ?? ''] ?? null;
if (!$src) {
    http_response_code(404);
    exit;
}

set_time_limit(0);
ignore_user_abort(true);
header('Content-Type: video/mp2t');
header('Cache-Control: no-store');
header('X-Accel-Buffering: no');
if (function_exists('apache_setenv')) {
    @apache_setenv('no-gzip', '1');
}
while (ob_get_level()) {
    ob_end_flush();
}
ob_implicit_flush(true);

$cmd = [
    'ffmpeg', '-hide_banner', '-loglevel', 'fatal',
    '-fflags', '+genpts+discardcorrupt',
    '-avoid_negative_ts', 'make_zero',
    '-analyzeduration', '1000000', '-probesize', '1000000',
    '-i', $src,
    '-map', '0:v:0', '-map', '0:a:0',
    '-c:v', 'copy',
    '-c:a', 'aac', '-ac', '2', '-ar', '48000', '-b:a', '128k',
    '-muxdelay', '0', '-muxpreload', '0',
    '-f', 'mpegts', '-mpegts_flags', 'resend_headers', '-flush_packets', '1',
    'pipe:1',
];
$proc = proc_open($cmd, [
    0 => ['file', '/dev/null', 'r'],
    1 => ['pipe', 'w'],
    2 => ['file', '/tmp/iptv-ffmpeg.log', 'a'],
], $pipes, null, null, ['bypass_shell' => true]);
if (!is_resource($proc)) {
    http_response_code(500);
    exit;
}

stream_set_blocking($pipes[1], false);
while (true) {
    if (connection_aborted()) {
        break;
    }
    $st = proc_get_status($proc);
    $chunk = fread($pipes[1], 65536);
    if ($chunk !== false && $chunk !== '') {
        echo $chunk;
        flush();
        continue;
    }
    if (empty($st['running'])) {
        break;
    }
    usleep(20000);
}
fclose($pipes[1]);
$st = proc_get_status($proc);
if (!empty($st['pid']) && function_exists('posix_kill')) {
    @posix_kill((int) $st['pid'], 15);
}
proc_terminate($proc);
proc_close($proc);
