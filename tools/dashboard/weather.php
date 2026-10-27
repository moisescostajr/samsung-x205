<?php
header('Content-Type: application/json');
header('Cache-Control: public, max-age=600');

$cache = '/tmp/homedash-weather.json';
if (is_file($cache) && (time() - filemtime($cache)) < 600) {
    readfile($cache);
    exit;
}

function http_get($url) {
    $ctx = stream_context_create([
        'http' => [
            'timeout' => 8,
            'header' => "User-Agent: HomeDash/1\r\n",
        ],
        'ssl' => ['verify_peer' => true, 'verify_peer_name' => true],
    ]);
    return @file_get_contents($url, false, $ctx);
}

function sky_label($code) {
    $map = [
        0 => 'Clear', 1 => 'Mostly clear', 2 => 'Partly cloudy', 3 => 'Overcast',
        45 => 'Fog', 48 => 'Fog',
        51 => 'Drizzle', 53 => 'Drizzle', 55 => 'Drizzle',
        61 => 'Rain', 63 => 'Rain', 65 => 'Heavy rain',
        71 => 'Snow', 73 => 'Snow', 75 => 'Snow',
        80 => 'Showers', 81 => 'Showers', 82 => 'Heavy showers',
        95 => 'Thunder', 96 => 'Thunder', 99 => 'Thunder',
    ];
    return $map[(int) $code] ?? '—';
}

function compass($deg) {
    $pts = ['N', 'NE', 'E', 'SE', 'S', 'SW', 'W', 'NW'];
    return $pts[(int) round((((float) $deg) % 360) / 45) % 8];
}

$geo = json_decode(http_get('https://get.geojs.io/v1/ip/geo.json') ?: 'null', true);
if (!$geo || !isset($geo['latitude'], $geo['longitude'])) {
    $geo = json_decode(http_get('http://ip-api.com/json/?fields=status,city,country,lat,lon') ?: 'null', true);
    if (($geo['status'] ?? '') === 'success') {
        $geo = [
            'city' => $geo['city'] ?? '',
            'country' => $geo['country'] ?? '',
            'latitude' => $geo['lat'],
            'longitude' => $geo['lon'],
        ];
    } else {
        http_response_code(502);
        echo json_encode(['ok' => false, 'error' => 'geo failed']);
        exit;
    }
}

$lat = (float) $geo['latitude'];
$lon = (float) $geo['longitude'];
$city = trim(($geo['city'] ?? '').((!empty($geo['country']) ? ', '.$geo['country'] : '')));

$wxUrl = 'https://api.open-meteo.com/v1/forecast?latitude='.rawurlencode((string) $lat)
    .'&longitude='.rawurlencode((string) $lon)
    .'&current=temperature_2m,weather_code,wind_speed_10m,wind_direction_10m'
    .'&daily=weather_code,temperature_2m_max,temperature_2m_min'
    .'&timezone=auto&forecast_days=5';
$wx = json_decode(http_get($wxUrl) ?: 'null', true);
if (!$wx || empty($wx['current'])) {
    http_response_code(502);
    echo json_encode(['ok' => false, 'error' => 'forecast failed']);
    exit;
}

$cur = $wx['current'];
$daily = $wx['daily'] ?? [];
$days = [];
foreach ($daily['time'] ?? [] as $i => $date) {
    $days[] = [
        'd' => date('D', strtotime($date.' UTC')),
        't' => round((float) ($daily['temperature_2m_max'][$i] ?? 0)).'° / '
            .round((float) ($daily['temperature_2m_min'][$i] ?? 0)).'°',
        's' => sky_label($daily['weather_code'][$i] ?? 0),
        'code' => (int) ($daily['weather_code'][$i] ?? 0),
    ];
}

$out = [
    'ok' => true,
    'place' => $city !== '' ? $city : (round($lat, 2).', '.round($lon, 2)),
    'now' => round((float) $cur['temperature_2m']).'°',
    'sky' => sky_label($cur['weather_code'] ?? 0),
    'code' => (int) ($cur['weather_code'] ?? 0),
    'wind' => round((float) $cur['wind_speed_10m']).' km/h '.compass($cur['wind_direction_10m'] ?? 0),
    'days' => $days,
    'source' => 'Open-Meteo · IP location',
];
$json = json_encode($out, JSON_UNESCAPED_UNICODE);
@file_put_contents($cache, $json);
echo $json;
