<?php
header('Content-Type: application/json');
header('Cache-Control: no-store');

$cfg = is_file(__DIR__.'/config.php') ? require __DIR__.'/config.php' : [];
$rows = [];
foreach ($cfg['sip_contacts'] ?? [] as $c) {
    if (!is_array($c) || empty($c['name']) || empty($c['number'])) {
        continue;
    }
    $rows[] = [
        'name' => (string) $c['name'],
        'number' => (string) $c['number'],
    ];
}
echo json_encode(['ok' => true, 'contacts' => $rows], JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES);
