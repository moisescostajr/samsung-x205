<?php
header('Content-Type: application/json');
header('Cache-Control: no-store');

$cfg = is_file(__DIR__.'/config.php') ? require __DIR__.'/config.php' : [];
if (empty($cfg['sip']['server']) || empty($cfg['sip']['user'])) {
    http_response_code(503);
    echo json_encode(['ok' => false, 'error' => 'sip not configured']);
    exit;
}

$action = preg_replace('/[^a-z]/', '', strtolower($_GET['action'] ?? 'status'));
$allowed = ['status' => 'GET', 'dial' => 'POST', 'hangup' => 'POST', 'answer' => 'POST', 'dtmf' => 'POST'];
if (!isset($allowed[$action])) {
    http_response_code(400);
    echo json_encode(['ok' => false, 'error' => 'bad action']);
    exit;
}

$method = $allowed[$action];
$body = file_get_contents('php://input');
$opts = [
    'http' => [
        'method' => $method,
        'timeout' => 4,
        'ignore_errors' => true,
        'header' => "Accept: application/json\r\n",
    ],
];
if ($method === 'POST') {
    $opts['http']['header'] .= "Content-Type: application/json\r\n";
    $opts['http']['content'] = $body !== '' ? $body : '{}';
}

$raw = @file_get_contents('http://127.0.0.1:8765/'.$action, false, stream_context_create($opts));
if ($raw === false) {
    http_response_code(503);
    echo json_encode(['ok' => false, 'error' => 'SIP client not running', 'state' => 'stopped']);
    exit;
}
echo $raw;
