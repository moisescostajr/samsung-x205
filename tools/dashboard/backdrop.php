<?php
header('Content-Type: application/json');
header('Cache-Control: public, max-age=1800');

function http_get($url) {
    $ctx = stream_context_create([
        'http' => [
            'timeout' => 8,
            'header' => "User-Agent: HomeDash/1\r\n",
        ],
    ]);
    return @file_get_contents($url, false, $ctx);
}

$images = [];

foreach ([0, 8] as $idx) {
    $raw = http_get('https://www.bing.com/HPImageArchive.aspx?format=js&idx='.$idx.'&n=8&mkt=en-US');
    if (!$raw) {
        continue;
    }
    $data = json_decode($raw, true);
    foreach ($data['images'] ?? [] as $im) {
        $path = $im['url'] ?? '';
        if ($path === '') {
            continue;
        }
        $images[] = [
            'url' => 'https://www.bing.com'.$path,
            'title' => $im['title'] ?? '',
            'credit' => $im['copyright'] ?? 'Bing daily photo',
        ];
    }
}

$earth = [
    ['id' => '1003', 'credit' => 'Google Earth View · Great Barrier Reef, Australia'],
    ['id' => '1012', 'credit' => 'Google Earth View'],
    ['id' => '1033', 'credit' => 'Google Earth View'],
    ['id' => '1047', 'credit' => 'Google Earth View'],
    ['id' => '2000', 'credit' => 'Google Earth View'],
    ['id' => '6235', 'credit' => 'Google Earth View'],
    ['id' => '7008', 'credit' => 'Google Earth View'],
    ['id' => '1024', 'credit' => 'Google Earth View'],
];
foreach ($earth as $e) {
    $images[] = [
        'url' => 'https://www.gstatic.com/prettyearth/assets/full/'.$e['id'].'.jpg',
        'title' => '',
        'credit' => $e['credit'],
    ];
}

if (!$images) {
    $images[] = [
        'url' => 'https://www.gstatic.com/prettyearth/assets/full/6235.jpg',
        'title' => '',
        'credit' => 'Google Earth View',
    ];
}

echo json_encode(['images' => $images], JSON_UNESCAPED_SLASHES);
