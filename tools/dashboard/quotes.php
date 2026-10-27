<?php
header('Content-Type: application/json');
header('Cache-Control: no-store');

$wanted = [
    ['id' => 'BZ=F',  'name' => 'Brent Crude Oil', 'sym' => 'BZ=F'],
    ['id' => 'GC=F',  'name' => 'Gold',            'sym' => 'GC=F'],
    ['id' => '^GSPC', 'name' => 'S&P 500',         'sym' => 'GSPC'],
    ['id' => 'JPY=X', 'name' => 'USD / JPY',       'sym' => 'USDJPY'],
];

function yahoo_chart($symbol) {
    $url = 'https://query1.finance.yahoo.com/v8/finance/chart/'
        .rawurlencode($symbol).'?interval=1m&range=1d';
    $ctx = stream_context_create([
        'http' => [
            'timeout' => 8,
            'header' => "User-Agent: Mozilla/5.0 HomeDash/1\r\nAccept: application/json\r\n",
        ],
    ]);
    $raw = @file_get_contents($url, false, $ctx);
    if ($raw === false) {
        return null;
    }
    $data = json_decode($raw, true);
    $meta = $data['chart']['result'][0]['meta'] ?? null;
    if (!$meta || !isset($meta['regularMarketPrice'])) {
        return null;
    }
    $px = (float) $meta['regularMarketPrice'];
    $prev = (float) ($meta['chartPreviousClose'] ?? $meta['previousClose'] ?? $px);
    $chg = $px - $prev;
    $pct = $prev ? ($chg / $prev) * 100 : 0;
    $close = $data['chart']['result'][0]['indicators']['quote'][0]['close'] ?? [];
    $series = [];
    foreach ($close as $v) {
        if ($v === null || $v === '') {
            continue;
        }
        $series[] = round((float) $v, 4);
    }
    $n = count($series);
    if ($n > 90) {
        $step = ($n - 1) / 79;
        $slim = [];
        for ($i = 0; $i < 80; $i++) {
            $slim[] = $series[(int) round($i * $step)];
        }
        $series = $slim;
    }
    return [
        'price' => $px,
        'change' => $chg,
        'pct' => $pct,
        'currency' => $meta['currency'] ?? '',
        'time' => (int) ($meta['regularMarketTime'] ?? time()),
        'series' => $series,
    ];
}

$rows = [];
foreach ($wanted as $w) {
    $q = yahoo_chart($w['id']);
    $rows[] = [
        'id' => $w['id'],
        'sym' => $w['sym'],
        'name' => $w['name'],
        'price' => $q['price'] ?? null,
        'change' => $q['change'] ?? null,
        'pct' => $q['pct'] ?? null,
        'currency' => $q['currency'] ?? '',
        'time' => $q['time'] ?? null,
        'series' => $q['series'] ?? [],
        'ok' => $q !== null,
    ];
}

echo json_encode(['quotes' => $rows, 'source' => 'Yahoo Finance'], JSON_UNESCAPED_SLASHES);
