<?php
$earthCdn = 'https://www.gstatic.com/prettyearth/assets/full';
$now = date('D j M H:i');

$nav = [
    ['id' => 'home', 'label' => 'Home', 'icon' => 'home'],
    ['id' => 'weather', 'label' => 'Weather', 'icon' => 'weather'],
    ['id' => 'news', 'label' => 'News', 'icon' => 'news'],
    ['id' => 'stocks', 'label' => 'Stocks', 'icon' => 'stocks'],
    ['id' => 'cameras', 'label' => 'IP cameras', 'icon' => 'camera'],
    ['id' => 'calls', 'label' => 'Video calls', 'icon' => 'video'],
    ['id' => 'iptv', 'label' => 'IPTV', 'icon' => 'tv'],
];

$local = [];
if (is_file(__DIR__.'/config.php')) {
    $local = require __DIR__.'/config.php';
}

$hero = [
    'image' => $earthCdn.'/6235.jpg',
    'title' => 'Good morning',
    'caption' => 'Sample dashboard · copy config.sample.php to config.php for cameras and IPTV.',
    'credit' => 'Photo: Google Earth View',
    'stats' => [
        ['label' => 'Outside', 'value' => '12°'],
        ['label' => 'Index', 'value' => '+0.6%'],
        ['label' => 'Cameras', 'value' => '0 / 0'],
        ['label' => 'Next rain', 'value' => 'Wed'],
    ],
];

$weather = [
    'place' => 'Sample city',
    'now' => '12°',
    'sky' => 'Partly cloudy',
    'wind' => '4 m/s SW',
    'days' => [
        ['d' => 'Mon', 't' => '12° / 6°', 's' => 'Cloud'],
        ['d' => 'Tue', 't' => '14° / 7°', 's' => 'Sun'],
        ['d' => 'Wed', 't' => '11° / 5°', 's' => 'Rain'],
        ['d' => 'Thu', 't' => '9° / 4°', 's' => 'Rain'],
        ['d' => 'Fri', 't' => '10° / 3°', 's' => 'Cloud'],
    ],
];
$news = [
    ['src' => 'Wire', 'title' => 'Morning fog lifts over the city by midday', 'ago' => '22 min'],
    ['src' => 'Local', 'title' => 'Weekend markets return to the square', 'ago' => '1 h'],
    ['src' => 'Markets', 'title' => 'Stocks open slightly higher', 'ago' => '3 h'],
    ['src' => 'Weather', 'title' => 'Clearer skies expected through Tuesday', 'ago' => '5 h'],
];
$stocks = [
    ['sym' => 'AAA', 'name' => 'Example A', 'px' => '12.40', 'chg' => '+1.2%', 'up' => true],
    ['sym' => 'BBB', 'name' => 'Example B', 'px' => '42.61', 'chg' => '-0.4%', 'up' => false],
    ['sym' => 'CCC', 'name' => 'Example C', 'px' => '52.04', 'chg' => '+0.7%', 'up' => true],
    ['sym' => 'DDD', 'name' => 'Example D', 'px' => '16.22', 'chg' => '+2.1%', 'up' => true],
];
$cameras = $local['cameras'] ?? [];
$hero['stats'][2]['value'] = (string) count($cameras).' / '.count($cameras);
if ($cameras) {
    $hero['caption'] = 'Cam '.implode(' and Cam ', array_map(static function ($c) {
        return preg_replace('/^Cam\s+/i', '', $c['name']);
    }, $cameras)).' online.';
}
$xtream = $local['xtream'] ?? null;
$sipContacts = array_values(array_filter($local['sip_contacts'] ?? [], static function ($c) {
    return is_array($c) && !empty($c['name']) && !empty($c['number']);
}));
$sipPub = [
    'server' => $local['sip']['server'] ?? '',
    'user' => $local['sip']['user'] ?? '',
    'contacts' => $sipContacts,
];
$channels = [
    ['name' => 'Channel 1 HD', 'now' => 'Morning show', 'num' => '1'],
    ['name' => 'Channel 2 HD', 'now' => 'Kids', 'num' => '2'],
    ['name' => 'Channel 3 HD', 'now' => 'News', 'num' => '3'],
    ['name' => 'Channel 4 HD', 'now' => 'Drama', 'num' => '4'],
    ['name' => 'Channel 5', 'now' => 'Documentary', 'num' => '5'],
    ['name' => 'Channel 6', 'now' => 'Comedy', 'num' => '6'],
];

function icon_svg($name) {
    $paths = [
        'home' => '<path d="M4 11l8-7 8 7"/><path d="M6 10v10h12V10"/>',
        'menu' => '<path d="M4 7h16M4 12h16M4 17h16"/>',
        'weather' => '<path d="M17.5 19H9a7 7 0 1 1 6.71-9h1.79a4.5 4.5 0 1 1 0 9Z"/>',
        'news' => '<path d="M5 4h10v16H5z"/><path d="M15 7h4v11a2 2 0 0 1-2 2H7"/><path d="M8 8h4M8 12h4M8 16h2"/>',
        'stocks' => '<path d="M4 16l5-5 4 3 7-8"/><path d="M15 6h5v5"/>',
        'camera' => '<path d="M4 8h3l2-2h6l2 2h3v11H4z"/><circle cx="12" cy="14" r="3.5"/>',
        'video' => '<path d="M16 8v8l6 3V5z"/><rect x="2" y="6" width="14" height="12" rx="2"/>',
        'tv' => '<rect x="3" y="5" width="18" height="12" rx="2"/><path d="M8 21h8M12 17v4"/>',
    ];
    $d = $paths[$name] ?? $paths['home'];
    return '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">'.$d.'</svg>';
}
?>
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="mobile-web-app-capable" content="yes">
  <title>Home</title>
  <link rel="stylesheet" href="bootstrap.min.css">
  <style>
    :root {
      --bg: #0f1419;
      --panel: #171e27;
      --line: #243041;
      --text: #e8eef6;
      --muted: #8b9bb0;
      --good: #3dd68c;
      --bad: #ff6b7a;
      --side: 240px;
      --side-min: 72px;
    }
    html, body { background: var(--bg); color: var(--text); height: 100%; margin: 0; }
    body { font-family: "Segoe UI", system-ui, sans-serif; overflow: hidden; }
    .shell { display: flex; height: 100vh; }
    .side {
      flex: 0 0 var(--side); width: var(--side);
      background: #121820; border-right: 1px solid var(--line);
      display: flex; flex-direction: column;
      transition: flex-basis .22s ease, width .22s ease; overflow: hidden;
    }
    .shell.collapsed .side { flex-basis: var(--side-min); width: var(--side-min); }
    .side-top { display: flex; align-items: center; gap: .6rem; padding: 1rem .85rem .6rem; }
    .toggle {
      flex: 0 0 40px; width: 40px; height: 40px;
      border: 1px solid var(--line); background: #1a222c; color: var(--text);
      border-radius: .6rem; display: grid; place-items: center; padding: 0;
    }
    .toggle svg, .nav-link svg { width: 20px; height: 20px; }
    .brand { letter-spacing: .06em; font-weight: 700; white-space: nowrap; }
    .shell.collapsed .brand, .shell.collapsed .side-meta, .shell.collapsed .nav-label {
      opacity: 0; pointer-events: none;
    }
    .nav-col { padding: .4rem .7rem; display: flex; flex-direction: column; gap: .25rem; }
    .nav-link {
      color: var(--muted); border-radius: .6rem;
      display: flex; align-items: center; gap: .75rem;
      padding: .7rem .7rem; white-space: nowrap;
    }
    .nav-link svg { flex: 0 0 20px; }
    .nav-link.active, .nav-link:hover { color: #fff; background: #1e2834; }
    .side-meta { padding: 1rem .95rem; color: var(--muted); font-size: .8rem; margin-top: auto; white-space: nowrap; }
    .main { flex: 1; overflow: auto; padding: 1.25rem 1.4rem 2rem; }
    .card-panel { background: var(--panel); border: 1px solid var(--line); border-radius: 1rem; }
    .hero-stage {
      position: relative; height: min(52vh, 440px); overflow: hidden;
      background: #0b1016; border-radius: 1rem 1rem 0 0;
    }
    .hero-stage img {
      position: absolute; inset: 0; width: 100%; height: 100%;
      object-fit: cover; opacity: 0; transition: opacity 1.4s ease;
    }
    .hero-stage img.show { opacity: 1; }
    .hero-overlay {
      position: absolute; left: 0; right: 0; bottom: 0; z-index: 2;
      padding: 2.2rem 1.1rem .9rem;
      background: linear-gradient(transparent, rgba(8,12,18,.78));
      color: #eef3f8;
    }
    .hero-overlay .place { font-weight: 600; }
    .hero-photo { width: 100%; height: min(48vh, 380px); object-fit: cover; display: block; border-radius: 1rem 1rem 0 0; }
    .kpi-value { font-size: 1.7rem; font-weight: 700; }
    .hero-stat { font-size: 1.25rem; font-weight: 700; }
    .up { color: var(--good); } .down { color: var(--bad); } .muted { color: var(--muted); }
    .table { color: var(--text); }
    .table > :not(caption) > * > * { background: transparent; color: var(--text); border-color: var(--line); }
    .panel { display: none; } .panel.active { display: block; }
    .cam-tile { position: relative; overflow: hidden; border-radius: .9rem; border: 1px solid var(--line); background: #0b1016; cursor: pointer; }
    .cam-tile img { width: 100%; height: 200px; object-fit: cover; display: block; }
    .live-tile img { height: min(38vh, 300px); background: #0b1016; }
    .crumb {
      display: flex; align-items: center; gap: .35rem; flex-wrap: wrap;
      margin-bottom: .85rem; font-size: .95rem;
    }
    .crumb button {
      border: 0; background: none; color: var(--muted); padding: 0; cursor: pointer;
    }
    .crumb button:hover { color: var(--text); }
    .crumb-sep { color: var(--muted); }
    .crumb-now { color: var(--text); }
    #panel-cameras.zoomed.active {
      display: flex; flex-direction: column; height: calc(100vh - 2.5rem);
    }
    #panel-cameras.zoomed .cam-grid { display: none; }
    .cam-zoom { display: none; flex: 1; min-height: 0; }
    #panel-cameras.zoomed .cam-zoom { display: flex; flex-direction: column; }
    .cam-zoom-frame {
      flex: 1; min-height: 0; position: relative; overflow: hidden;
      border-radius: 1rem; border: 1px solid var(--line); background: #0b1016;
    }
    .cam-zoom-frame img {
      width: 100%; height: 100%; object-fit: cover; display: block;
    }
    .cam-tag {
      position: absolute; left: .7rem; bottom: .7rem;
      background: rgba(12,16,22,.72); color: #fff; padding: .2rem .55rem;
      border-radius: 99px; font-size: .75rem;
    }
    .cam-dot { width: .45rem; height: .45rem; border-radius: 99px; background: var(--good); display: inline-block; margin-right: .35rem; }
    .call-btn {
      border: 1px solid var(--line); background: #1a222c; color: var(--text);
      border-radius: .55rem; padding: .35rem .8rem;
    }
    .ch-num {
      width: 2rem; height: 2rem; border-radius: .5rem; background: #1a222c;
      display: grid; place-items: center; font-size: .8rem; color: var(--muted);
    }
    .iptv-player {
      width: 100%; height: min(38vh, 300px);
      background: #000; border-radius: 1rem 1rem 0 0; display: block;
    }
    .ch-list { max-height: min(38vh, 320px); overflow: auto; }
    .ch-row { cursor: pointer; }
    .ch-row.active { background: #1e2834; }
    .ch-group { padding: .45rem .9rem; font-size: .75rem; text-transform: uppercase; letter-spacing: .04em; color: var(--muted); background: #121820; position: sticky; top: 0; }
    .stock-item + .stock-item { border-top: 1px solid var(--line); }
    .stock-row {
      display: flex; align-items: center; gap: .75rem;
      width: 100%; border: 0; background: transparent; color: inherit;
      text-align: left; padding: .9rem 1rem; cursor: pointer;
    }
    .stock-item.open .stock-row { background: #1e2834; }
    .stock-chevron {
      width: 18px; height: 18px; flex: 0 0 18px; color: var(--muted);
      transition: transform .18s ease;
    }
    .stock-item.open .stock-chevron { transform: rotate(90deg); color: var(--text); }
    .stock-name { flex: 1; min-width: 0; }
    .stock-sym { font-size: .75rem; }
    .stock-px { font-weight: 700; font-variant-numeric: tabular-nums; }
    .stock-chg { min-width: 4.4rem; text-align: right; font-variant-numeric: tabular-nums; }
    .stock-chart-wrap { display: none; padding: .15rem 1rem 1rem; }
    .stock-item.open .stock-chart-wrap { display: block; }
    .stock-chart { width: 100%; height: 150px; display: block; }
    .wx-icon { width: 36px; height: 36px; display: block; margin: .35rem auto; color: #8ec5ff; }
    .wx-icon.sun { color: #f0d27a; }
    .wx-icon-lg { width: 48px; height: 48px; margin: 0 .5rem 0 0; }
    .sip-phone { max-width: 420px; }
    .sip-contacts { min-height: 12rem; }
    .sip-contact {
      display: flex; align-items: center; gap: .75rem;
      width: 100%; border: 0; background: transparent; color: inherit;
      text-align: left; padding: .85rem 1rem; cursor: pointer;
    }
    .sip-contact + .sip-contact { border-top: 1px solid var(--line); }
    .sip-contact:hover, .sip-contact:focus { background: #1e2834; }
    .sip-avatar {
      width: 2.2rem; height: 2.2rem; border-radius: 99px; flex: 0 0 2.2rem;
      background: #1a222c; display: grid; place-items: center; font-weight: 700;
    }
    .sip-stage {
      background: #0b1016; min-height: 150px;
      display: flex; flex-direction: column; justify-content: flex-end;
      padding: 1.1rem 1.15rem .95rem;
    }
    .sip-number {
      font-size: 2rem; font-weight: 700; letter-spacing: .06em;
      min-height: 2.4rem; font-variant-numeric: tabular-nums; word-break: break-all;
    }
    .sip-pad {
      display: grid; grid-template-columns: repeat(3, 1fr); gap: .55rem;
      padding: 1rem;
    }
    .sip-key {
      border: 1px solid var(--line); background: #1a222c; color: var(--text);
      border-radius: .8rem; min-height: 3.4rem;
      display: flex; flex-direction: column; align-items: center; justify-content: center;
    }
    .sip-key .letters { font-size: .65rem; color: var(--muted); letter-spacing: .08em; }
    .sip-actions {
      display: grid; grid-template-columns: 1fr 1.4fr 1fr; gap: .55rem;
      padding: 0 1rem 1rem;
    }
    .sip-actions button { min-height: 3.1rem; border-radius: .8rem; }
    .sip-call { background: #1f6a45; border: 0; color: #fff; font-weight: 700; }
    .sip-hang { background: #8a2a34; border: 0; color: #fff; font-weight: 700; }
    .sip-answer { background: #1f6a45; border: 0; color: #fff; font-weight: 700; }
    .sip-dot {
      width: .55rem; height: .55rem; border-radius: 99px; display: inline-block;
      margin-right: .4rem; background: var(--muted);
    }
    .sip-dot.on { background: var(--good); }
    .sip-dot.warn { background: #f0d27a; }
    .sip-dot.off { background: var(--bad); }
  </style>
</head>
<body>
<div class="shell" id="shell">
  <aside class="side">
    <div class="side-top">
      <button class="toggle" id="navToggle" type="button" aria-label="Collapse menu"><?= icon_svg('menu') ?></button>
      <div class="brand">HOME</div>
    </div>
    <nav class="nav-col">
      <?php foreach ($nav as $i => $item): ?>
      <a class="nav-link<?= $i === 0 ? ' active' : '' ?>" href="#<?= htmlspecialchars($item['id']) ?>" data-panel="<?= htmlspecialchars($item['id']) ?>">
        <?= icon_svg($item['icon']) ?>
        <span class="nav-label"><?= htmlspecialchars($item['label']) ?></span>
      </a>
      <?php endforeach; ?>
    </nav>
    <div class="side-meta"><?= htmlspecialchars($now) ?></div>
  </aside>
  <main class="main">
    <section class="panel active" id="panel-home">
      <div class="card-panel overflow-hidden">
        <div class="hero-stage">
          <img id="heroA" class="show" src="<?= htmlspecialchars($hero['image']) ?>" alt="" referrerpolicy="no-referrer">
          <img id="heroB" alt="" referrerpolicy="no-referrer">
          <div class="hero-overlay">
            <div class="place" id="heroPlace"><?= htmlspecialchars($hero['title']) ?></div>
            <div class="muted small" id="heroCredit"><?= htmlspecialchars($hero['credit']) ?></div>
          </div>
        </div>
        <div class="p-3 p-md-4">
          <div class="muted mb-3"><?= htmlspecialchars($hero['caption']) ?></div>
          <div class="row g-3">
            <?php foreach ($hero['stats'] as $s): ?>
            <div class="col-6 col-md-3">
              <div class="muted small"><?= htmlspecialchars($s['label']) ?></div>
              <div class="hero-stat"<?= $s['label'] === 'Outside' ? ' id="homeOutside"' : '' ?>><?= htmlspecialchars($s['value']) ?></div>
            </div>
            <?php endforeach; ?>
          </div>
        </div>
      </div>
    </section>

    <section class="panel" id="panel-weather">
      <div class="d-flex justify-content-between align-items-end mb-3">
        <h1 class="h4 mb-0">Weather</h1>
        <div class="muted small" id="weatherSource">Locating…</div>
      </div>
      <div class="card-panel p-4 mb-3">
        <div class="muted small" id="weatherPlace"><?= htmlspecialchars($weather['place']) ?></div>
        <div class="d-flex align-items-end gap-3">
          <span id="weatherNowIcon"></span>
          <div class="kpi-value" id="weatherNow"><?= htmlspecialchars($weather['now']) ?></div>
          <div>
            <div id="weatherSky"><?= htmlspecialchars($weather['sky']) ?></div>
            <div class="muted small" id="weatherWind"><?= htmlspecialchars($weather['wind']) ?></div>
          </div>
        </div>
      </div>
      <div class="row g-3" id="weatherDays">
        <?php foreach ($weather['days'] as $d): ?>
        <div class="col">
          <div class="card-panel p-3 text-center h-100">
            <div class="muted small"><?= htmlspecialchars($d['d']) ?></div>
            <div class="mt-1"><?= htmlspecialchars($d['t']) ?></div>
            <div class="muted small"><?= htmlspecialchars($d['s']) ?></div>
          </div>
        </div>
        <?php endforeach; ?>
      </div>
    </section>

    <section class="panel" id="panel-news">
      <h1 class="h4 mb-3">News</h1>
      <div class="card-panel p-0 overflow-hidden">
        <?php foreach ($news as $n): ?>
        <div class="p-3" style="border-bottom:1px solid var(--line)">
          <div class="muted small"><?= htmlspecialchars($n['src']) ?> · <?= htmlspecialchars($n['ago']) ?></div>
          <div><?= htmlspecialchars($n['title']) ?></div>
        </div>
        <?php endforeach; ?>
      </div>
    </section>

    <section class="panel" id="panel-stocks">
      <div class="d-flex justify-content-between align-items-end mb-3">
        <h1 class="h4 mb-0">Stocks</h1>
        <div class="muted small" id="stockStatus">Yahoo Finance</div>
      </div>
      <div class="card-panel overflow-hidden" id="stockList">
        <?php foreach ($stocks as $s): ?>
        <div class="stock-item">
          <button type="button" class="stock-row">
            <svg class="stock-chevron" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M9 6l6 6-6 6"/></svg>
            <div class="stock-name">
              <div><?= htmlspecialchars($s['name']) ?></div>
              <div class="muted stock-sym"><?= htmlspecialchars($s['sym']) ?></div>
            </div>
            <div class="text-end">
              <div class="stock-px"><?= htmlspecialchars($s['px']) ?></div>
              <div class="stock-chg <?= $s['up'] ? 'up' : 'down' ?>"><?= htmlspecialchars($s['chg']) ?></div>
            </div>
          </button>
        </div>
        <?php endforeach; ?>
      </div>
    </section>

    <section class="panel" id="panel-cameras">
      <nav class="crumb" aria-label="Camera location">
        <button type="button" id="camBack">IP cameras</button>
        <span id="camCrumbTail" hidden><span class="crumb-sep">/</span> <span class="crumb-now" id="camCrumbName"></span></span>
      </nav>
      <div class="cam-grid row g-3">
        <?php if (!$cameras): ?>
        <div class="col-12"><div class="muted">No cameras configured. Copy config.sample.php to config.php.</div></div>
        <?php endif; ?>
        <?php foreach ($cameras as $c): ?>
        <div class="col-md-6">
          <div class="cam-tile live-tile" data-cam-name="<?= htmlspecialchars($c['name']) ?>">
            <img data-cam-src="<?= htmlspecialchars($c['url']) ?>" src="<?= htmlspecialchars($c['url']) ?>" alt="<?= htmlspecialchars($c['name']) ?>" referrerpolicy="no-referrer">
            <div class="cam-tag"><span class="cam-dot"></span><?= htmlspecialchars($c['name']) ?> · live</div>
          </div>
        </div>
        <?php endforeach; ?>
      </div>
      <div class="cam-zoom">
        <div class="cam-zoom-frame">
          <img id="camZoomImg" data-cam-src="" alt="" referrerpolicy="no-referrer">
          <div class="cam-tag"><span class="cam-dot"></span><span id="camZoomTag"></span></div>
        </div>
      </div>
    </section>

    <section class="panel" id="panel-calls">
      <div class="d-flex justify-content-between align-items-end mb-3">
        <h1 class="h4 mb-0">Video calls</h1>
        <div class="muted small" id="sipStatusLabel">SIP</div>
      </div>
      <div class="row g-3">
        <div class="col-lg-7">
          <div class="card-panel overflow-hidden sip-contacts">
            <div class="px-3 pt-3 pb-2 d-flex justify-content-between align-items-center">
              <div>Contacts</div>
              <div class="muted small" id="sipContactCount"></div>
            </div>
            <div id="sipContactList"></div>
          </div>
        </div>
        <div class="col-lg-5">
          <div class="sip-phone card-panel overflow-hidden">
            <div class="sip-stage">
              <div class="muted small" id="sipReg"><span class="sip-dot" id="sipDot"></span>Connecting…</div>
              <div class="sip-number" id="sipNumber"></div>
              <div class="muted small" id="sipPeer"></div>
            </div>
            <div class="sip-pad" id="sipPad"></div>
            <div class="sip-actions">
              <button class="call-btn" id="sipBack" type="button">⌫</button>
              <button class="sip-call" id="sipCall" type="button">Call</button>
              <button class="sip-hang" id="sipHang" type="button">End</button>
            </div>
            <div class="px-3 pb-3" id="sipAnswerWrap" hidden>
              <button class="sip-answer w-100" id="sipAnswer" type="button">Answer</button>
            </div>
          </div>
        </div>
      </div>
    </section>

    <section class="panel" id="panel-iptv">
      <h1 class="h4 mb-3">IPTV</h1>
      <div class="card-panel overflow-hidden mb-3 p-0">
        <video id="iptvPlayer" class="iptv-player" controls playsinline></video>
        <div class="p-3 d-flex align-items-center justify-content-between gap-3">
          <div>
            <div id="iptvNow">No channel</div>
            <div class="muted small" id="iptvStatus">Xtream · pick a channel</div>
          </div>
          <button class="call-btn" id="iptvPlay" type="button">Play</button>
        </div>
      </div>
      <div class="card-panel p-0 overflow-hidden">
        <div class="ch-list" id="iptvList">
          <?php foreach ($channels as $ch): ?>
          <div class="p-3 d-flex align-items-center gap-3 ch-row">
            <div class="ch-num"><?= htmlspecialchars($ch['num']) ?></div>
            <div>
              <div><?= htmlspecialchars($ch['name']) ?></div>
              <div class="muted small">Sample</div>
            </div>
          </div>
          <?php endforeach; ?>
        </div>
      </div>
    </section>
  </main>
</div>
<script>window.XTREAM = <?= $xtream ? json_encode($xtream, JSON_UNESCAPED_SLASHES | JSON_HEX_TAG | JSON_HEX_AMP) : 'null' ?>;
window.SIP = <?= $sipPub ? json_encode($sipPub, JSON_UNESCAPED_SLASHES | JSON_HEX_TAG | JSON_HEX_AMP) : 'null' ?>;</script>
<script src="mpegts.min.js"></script>
<script>
  const shell = document.getElementById("shell");
  document.getElementById("navToggle").addEventListener("click", () => shell.classList.toggle("collapsed"));
  const links = document.querySelectorAll("[data-panel]");
  const camPanel = document.getElementById("panel-cameras");
  const camZoomImg = document.getElementById("camZoomImg");
  const camZoomTag = document.getElementById("camZoomTag");
  const camCrumbTail = document.getElementById("camCrumbTail");
  const camCrumbName = document.getElementById("camCrumbName");
  let camTimer = null;

  function camImgs() {
    return document.querySelectorAll("[data-cam-src]");
  }
  function refreshCams() {
    camImgs().forEach((img) => {
      const base = img.dataset.camSrc;
      if (!base) return;
      const next = new Image();
      next.onload = () => { img.src = next.src; };
      next.src = base + (base.indexOf("?") >= 0 ? "&" : "?") + "t=" + Date.now();
    });
  }
  function setCamLive(on) {
    if (camTimer) {
      clearInterval(camTimer);
      camTimer = null;
    }
    if (on) {
      refreshCams();
      camTimer = setInterval(refreshCams, 2000);
    }
  }
  function closeCamZoom() {
    camPanel.classList.remove("zoomed");
    camZoomImg.dataset.camSrc = "";
    camZoomImg.removeAttribute("src");
    camCrumbTail.hidden = true;
  }
  function openCamZoom(name, url) {
    camZoomImg.dataset.camSrc = url;
    camZoomImg.alt = name;
    camZoomTag.textContent = name + " · live";
    camCrumbName.textContent = name;
    camCrumbTail.hidden = false;
    camPanel.classList.add("zoomed");
    refreshCams();
  }

  document.querySelectorAll(".cam-tile").forEach((tile) => {
    tile.addEventListener("click", () => {
      const img = tile.querySelector("[data-cam-src]");
      openCamZoom(tile.dataset.camName, img.dataset.camSrc);
    });
  });
  document.getElementById("camBack").addEventListener("click", closeCamZoom);

  links.forEach((a) => a.addEventListener("click", (e) => {
    e.preventDefault();
    const id = a.dataset.panel;
    document.querySelectorAll(".panel").forEach((p) => p.classList.toggle("active", p.id === "panel-" + id));
    links.forEach((l) => l.classList.toggle("active", l.dataset.panel === id));
    if (id !== "cameras") closeCamZoom();
    setCamLive(id === "cameras");
    if (id !== "iptv") stopIptv();
    if (id === "iptv") loadXtreamChannels();
    setHeroRotate(id === "home");
    setStocksLive(id === "stocks");
    setSipLive(id === "calls");
    if (id === "weather") loadWeather();
  }));

  document.getElementById("iptvPlay").addEventListener("click", () => {
    const v = document.getElementById("iptvPlayer");
    if (v.getAttribute("src") || window.iptvLive) stopIptv();
    else startIptv();
  });

  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
    }[c]));
  }
  let xtreamCats = {};
  let xtreamLoaded = false;
  let iptvPick = null;

  function xtreamApi(action) {
    const x = window.XTREAM;
    let u = x.api + "?username=" + encodeURIComponent(x.username) + "&password=" + encodeURIComponent(x.password);
    if (action) u += "&action=" + encodeURIComponent(action);
    return u;
  }
  function xtreamPlayUrl(streamId) {
    const x = window.XTREAM;
    return x.stream.replace(/\/$/, "") + "/live/" + encodeURIComponent(x.username) + "/"
      + encodeURIComponent(x.password) + "/" + streamId + ".ts";
  }
  function loadXtreamChannels() {
    if (!window.XTREAM || !window.XTREAM.api) return;
    if (xtreamLoaded) return;
    const list = document.getElementById("iptvList");
    const status = document.getElementById("iptvStatus");
    status.textContent = "Xtream · loading…";
    Promise.all([
      fetch(xtreamApi("get_live_categories")).then((r) => r.json()),
      fetch(xtreamApi("get_live_streams")).then((r) => r.json())
    ]).then(([cats, streams]) => {
      xtreamCats = {};
      (cats || []).forEach((c) => { xtreamCats[String(c.category_id)] = c.category_name; });
      xtreamStreams = streams || [];
      xtreamLoaded = true;
      const byCat = {};
      xtreamStreams.forEach((s) => {
        const id = String(s.category_id || "0");
        if (!byCat[id]) byCat[id] = [];
        byCat[id].push(s);
      });
      let html = "";
      Object.keys(byCat).forEach((id) => {
        html += "<div class=\"ch-group\">" + (xtreamCats[id] || "Live") + "</div>";
        byCat[id].forEach((s) => {
          html += "<div class=\"p-3 d-flex align-items-center gap-3 ch-row\" data-stream-id=\""
            + s.stream_id + "\" style=\"border-bottom:1px solid var(--line)\">"
            + "<div class=\"ch-num\">"             + (s.num || "") + "</div><div><div>"
            + esc(s.name) + "</div><div class=\"muted small\">id " + esc(s.stream_id) + "</div></div></div>";
        });
      });
      list.innerHTML = html;
      list.querySelectorAll(".ch-row").forEach((row) => {
        row.addEventListener("click", () => {
          const id = row.getAttribute("data-stream-id");
          iptvPick = xtreamStreams.find((s) => String(s.stream_id) === String(id));
          list.querySelectorAll(".ch-row").forEach((r) => r.classList.toggle("active", r === row));
          document.getElementById("iptvNow").textContent = iptvPick.name;
          startIptv();
        });
      });
      status.textContent = "Xtream · " + xtreamStreams.length + " channels";
    }).catch((e) => { status.textContent = "Xtream failed: " + e; });
  }

  function stopIptv() {
    const v = document.getElementById("iptvPlayer");
    const status = document.getElementById("iptvStatus");
    if (window.iptvLive) {
      try {
        window.iptvLive.pause();
        window.iptvLive.unload();
        window.iptvLive.detachMediaElement();
        window.iptvLive.destroy();
      } catch (e) {}
      window.iptvLive = null;
    }
    v.pause();
    v.removeAttribute("src");
    v.load();
    status.textContent = xtreamLoaded ? ("Xtream · " + xtreamStreams.length + " channels") : "Xtream · pick a channel";
    document.getElementById("iptvPlay").textContent = "Play";
  }

  function startIptv() {
    if (!iptvPick && xtreamStreams.length) iptvPick = xtreamStreams[0];
    if (!iptvPick) {
      document.getElementById("iptvStatus").textContent = "Pick a channel first";
      return;
    }
    stopIptv();
    const v = document.getElementById("iptvPlayer");
    const status = document.getElementById("iptvStatus");
    const url = window.XTREAM ? xtreamPlayUrl(iptvPick.stream_id) : "iptv.php?id=rtp1";
    document.getElementById("iptvNow").textContent = iptvPick.name;
    document.getElementById("iptvPlay").textContent = "Stop";
    status.textContent = "Starting " + iptvPick.name + "…";
    v.src = url;
    v.play().then(() => { status.textContent = "Xtream live · " + iptvPick.name; })
      .catch((e) => { status.textContent = String(e); });
  }

  const heroA = document.getElementById("heroA");
  const heroB = document.getElementById("heroB");
  const heroPlace = document.getElementById("heroPlace");
  const heroCredit = document.getElementById("heroCredit");
  let heroList = [];
  let heroI = 0;
  let heroFront = 0;
  let heroTimer = null;

  function heroCaption(item) {
    const t = (item.title || "").trim();
    const c = (item.credit || "").trim();
    if (t && c && c.indexOf(t) !== 0) return { place: t, credit: c };
    if (c) return { place: c.split(" (")[0], credit: c };
    return { place: "Home", credit: "" };
  }
  function showHero(item) {
    const next = 1 - heroFront;
    const el = next === 0 ? heroA : heroB;
    const prev = next === 0 ? heroB : heroA;
    const pre = new Image();
    pre.onload = () => {
      el.src = item.url;
      el.classList.add("show");
      prev.classList.remove("show");
      heroFront = next;
      const cap = heroCaption(item);
      heroPlace.textContent = cap.place;
      heroCredit.textContent = cap.credit;
    };
    pre.src = item.url;
  }
  function setHeroRotate(on) {
    if (heroTimer) {
      clearInterval(heroTimer);
      heroTimer = null;
    }
    if (!on || heroList.length < 2) return;
    heroTimer = setInterval(() => {
      heroI = (heroI + 1) % heroList.length;
      showHero(heroList[heroI]);
    }, 90 * 1000);
  }
  fetch("backdrop.php").then((r) => r.json()).then((d) => {
    heroList = d.images || [];
    if (!heroList.length) return;
    heroList.sort(() => Math.random() - 0.5);
    showHero(heroList[0]);
    if (document.getElementById("panel-home").classList.contains("active")) {
      setHeroRotate(true);
    }
  }).catch(() => {});

  let stockTimer = null;
  let stockOpen = null;
  function fmtPx(q) {
    const px = q.price;
    if (px == null) return "—";
    if (q.id === "JPY=X") return px.toFixed(2);
    if (q.id === "^GSPC" || q.id === "GC=F") {
      return px.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    }
    return px.toFixed(2);
  }
  function stockChartSvg(series, up) {
    const vals = (series || []).filter((v) => v != null && isFinite(v));
    if (vals.length < 2) {
      return '<div class="muted small">No chart for this session yet.</div>';
    }
    const w = 640, h = 150, pad = 10;
    const min = Math.min.apply(null, vals);
    const max = Math.max.apply(null, vals);
    const span = max - min || 1;
    const pts = vals.map((v, i) => {
      const x = pad + (i / (vals.length - 1)) * (w - pad * 2);
      const y = pad + (1 - (v - min) / span) * (h - pad * 2);
      return x.toFixed(1) + "," + y.toFixed(1);
    });
    const color = up ? "#3dd68c" : "#ff6b7a";
    const lastX = pts[pts.length - 1].split(",")[0];
    const area = "M" + pts.join(" L") + " L" + lastX + "," + (h - pad) + " L" + pad + "," + (h - pad) + " Z";
    const lo = min.toLocaleString("en-US", { maximumFractionDigits: 2 });
    const hi = max.toLocaleString("en-US", { maximumFractionDigits: 2 });
    return '<svg class="stock-chart" viewBox="0 0 ' + w + ' ' + h + '" preserveAspectRatio="none">'
      + '<path d="' + area + '" fill="' + color + '" fill-opacity="0.16"></path>'
      + '<polyline points="' + pts.join(" ") + '" fill="none" stroke="' + color
      + '" stroke-width="2.2" stroke-linejoin="round" stroke-linecap="round"></polyline></svg>'
      + '<div class="muted small d-flex justify-content-between mt-1"><span>Low ' + lo
      + '</span><span>Today</span><span>High ' + hi + '</span></div>';
  }
  function loadStocks() {
    const status = document.getElementById("stockStatus");
    fetch("quotes.php", { cache: "no-store" }).then((r) => r.json()).then((d) => {
      const list = document.getElementById("stockList");
      const times = [];
      list.innerHTML = (d.quotes || []).map((q) => {
        if (q.time) times.push(q.time);
        const up = (q.pct || 0) >= 0;
        const chg = q.ok ? ((up ? "+" : "") + q.pct.toFixed(2) + "%") : "—";
        const open = q.id === stockOpen ? " open" : "";
        return '<div class="stock-item' + open + '" data-stock="' + q.id + '">'
          + '<button type="button" class="stock-row">'
          + '<svg class="stock-chevron" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M9 6l6 6-6 6"/></svg>'
          + '<div class="stock-name"><div>' + q.name + '</div><div class="muted stock-sym">' + q.sym + '</div></div>'
          + '<div class="text-end"><div class="stock-px">' + fmtPx(q) + '</div>'
          + '<div class="stock-chg ' + (up ? "up" : "down") + '">' + chg + '</div></div>'
          + '</button><div class="stock-chart-wrap">' + stockChartSvg(q.series, up) + '</div></div>';
      }).join("");
      const ok = (d.quotes || []).filter((q) => q.ok).length;
      let stamp = "";
      if (times.length) {
        stamp = " · " + new Date(Math.max.apply(null, times) * 1000).toLocaleTimeString();
      }
      status.textContent = ok ? ("Yahoo · ~15 min delay" + stamp) : "Yahoo Finance · unavailable";
    }).catch(() => { status.textContent = "Yahoo Finance · unavailable"; });
  }
  document.getElementById("stockList").addEventListener("click", (e) => {
    const item = e.target.closest(".stock-item");
    if (!item) return;
    const id = item.getAttribute("data-stock");
    stockOpen = stockOpen === id ? null : id;
    document.querySelectorAll("#stockList .stock-item").forEach((el) => {
      el.classList.toggle("open", el.getAttribute("data-stock") === stockOpen);
    });
  });
  function setStocksLive(on) {
    if (stockTimer) {
      clearInterval(stockTimer);
      stockTimer = null;
    }
    if (!on) return;
    loadStocks();
    stockTimer = setInterval(loadStocks, 15000);
  }

  let sipTimer = null;
  let sipDigits = "";
  const sipKeys = [
    ["1", ""], ["2", "ABC"], ["3", "DEF"],
    ["4", "GHI"], ["5", "JKL"], ["6", "MNO"],
    ["7", "PQRS"], ["8", "TUV"], ["9", "WXYZ"],
    ["*", ""], ["0", "+"], ["#", ""]
  ];
  const sipPad = document.getElementById("sipPad");
  if (sipPad) {
    sipPad.innerHTML = sipKeys.map(([d, letters]) =>
      '<button type="button" class="sip-key" data-digit="' + d + '"><span>' + d
      + '</span>' + (letters ? '<span class="letters">' + letters + '</span>' : '') + '</button>'
    ).join("");
    sipPad.addEventListener("click", (e) => {
      const btn = e.target.closest("[data-digit]");
      if (!btn) return;
      const d = btn.getAttribute("data-digit");
      if (window.sipInCall) {
        sipApi("dtmf", { digit: d });
      }
      sipDigits += d;
      renderSipNumber();
    });
  }
  function renderSipNumber() {
    document.getElementById("sipNumber").textContent = sipDigits;
  }
  function sipApi(action, body) {
    const opts = { cache: "no-store" };
    if (body) {
      opts.method = "POST";
      opts.headers = { "Content-Type": "application/json" };
      opts.body = JSON.stringify(body);
    }
    return fetch("sip.php?action=" + action, opts).then((r) => r.json());
  }
  function sipStateText(d) {
    if (!d || !d.ok) return "SIP client not running";
    const map = {
      starting: "Starting…",
      registering: "Registering…",
      registered: "Ready",
      unregistered: "Not registered",
      dialing: "Calling…",
      incoming: "Incoming call",
      incall: "In call",
      stopped: "SIP client stopped"
    };
    return map[d.state] || d.state || "SIP";
  }
  function loadSip() {
    const label = document.getElementById("sipStatusLabel");
    const reg = document.getElementById("sipReg");
    const peer = document.getElementById("sipPeer");
    sipApi("status").then((d) => {
      window.sipInCall = d && (d.state === "incall" || d.state === "dialing");
      const ident = (window.SIP && window.SIP.user)
        ? (window.SIP.user + " @ " + window.SIP.server) : "SIP";
      label.textContent = ident;
      const text = sipStateText(d);
      const extra = d && d.last ? '<span class="d-block mt-1">' + esc(d.last) + '</span>' : '';
      reg.innerHTML = '<span class="sip-dot" id="sipDot"></span>' + esc(text) + extra;
      const dotEl = document.getElementById("sipDot");
      if (d && d.registered && (d.state === "registered" || d.state === "incall" || d.state === "dialing" || d.state === "incoming")) {
        dotEl.classList.add("on");
      } else if (d && (d.state === "registering" || d.state === "starting")) {
        dotEl.classList.add("warn");
      } else {
        dotEl.classList.add("off");
      }
      if (d && d.state === "incoming") {
        peer.textContent = d.peer || "Incoming";
        document.getElementById("sipAnswerWrap").hidden = false;
      } else {
        document.getElementById("sipAnswerWrap").hidden = true;
        if (d && (d.state === "incall" || d.state === "dialing")) peer.textContent = d.peer || "";
        else if (!sipDigits) peer.textContent = ident;
        else peer.textContent = "";
      }
    }).catch(() => {
      window.sipInCall = false;
      label.textContent = "SIP";
      reg.innerHTML = '<span class="sip-dot off"></span>SIP client not running';
    });
  }
  document.getElementById("sipBack").addEventListener("click", () => {
    sipDigits = sipDigits.slice(0, -1);
    renderSipNumber();
  });
  document.getElementById("sipCall").addEventListener("click", () => {
    if (!sipDigits) return;
    sipApi("dial", { number: sipDigits }).then(loadSip);
  });
  document.getElementById("sipHang").addEventListener("click", () => {
    sipApi("hangup", {}).then(() => {
      sipDigits = "";
      renderSipNumber();
      loadSip();
    });
  });
  document.getElementById("sipAnswer").addEventListener("click", () => {
    sipApi("answer", {}).then(loadSip);
  });
  let sipContacts = (window.SIP && window.SIP.contacts) ? window.SIP.contacts : [];
  function contactInitial(name) {
    const t = String(name || "?").trim();
    return (t.charAt(0) || "?").toUpperCase();
  }
  function renderSipContacts() {
    const list = document.getElementById("sipContactList");
    const count = document.getElementById("sipContactCount");
    count.textContent = sipContacts.length ? String(sipContacts.length) : "";
    if (!sipContacts.length) {
      list.innerHTML = '<div class="px-3 pb-3 muted small">No contacts configured.</div>';
      return;
    }
    list.innerHTML = sipContacts.map((c) =>
      '<button type="button" class="sip-contact" data-number="' + esc(c.number) + '" data-name="' + esc(c.name) + '">'
      + '<div class="sip-avatar">' + esc(contactInitial(c.name)) + '</div>'
      + '<div class="flex-grow-1 text-start"><div>' + esc(c.name) + '</div>'
      + '<div class="muted small">' + esc(c.number) + '</div></div>'
      + '</button>'
    ).join("");
  }
  function callStoredContact(name, number) {
    if (!number) return;
    sipDigits = number;
    renderSipNumber();
    document.getElementById("sipPeer").textContent = name || number;
    sipApi("dial", { number: number }).then(loadSip);
  }
  document.getElementById("sipContactList").addEventListener("click", (e) => {
    const row = e.target.closest(".sip-contact");
    if (!row) return;
    callStoredContact(row.getAttribute("data-name"), row.getAttribute("data-number"));
  });
  renderSipContacts();
  function setSipLive(on) {
    if (sipTimer) {
      clearInterval(sipTimer);
      sipTimer = null;
    }
    if (!on) return;
    loadSip();
    sipTimer = setInterval(loadSip, 1000);
  }

  function wxIcon(code, extra) {
    const c = Number(code) || 0;
    let cls = "wx-icon " + (extra || "");
    let body;
    if (c === 0 || c === 1) {
      cls += " sun";
      body = '<circle cx="12" cy="12" r="4"/><path d="M12 3v2M12 19v2M4.2 4.2l1.4 1.4M18.4 18.4l1.4 1.4M3 12h2M19 12h2M4.2 19.8l1.4-1.4M18.4 5.6l1.4-1.4"/>';
    } else if (c === 2) {
      cls += " sun";
      body = '<circle cx="10" cy="10" r="3"/><path d="M17.5 19H9a7 7 0 1 1 6.71-9h1.79a4.5 4.5 0 1 1 0 9Z"/>';
    } else if (c === 45 || c === 48) {
      body = '<path d="M4 10h16M3 14h18M6 18h12"/>';
    } else if (c >= 71 && c <= 77) {
      body = '<path d="M17.5 14H9a7 7 0 1 1 6.71-9h1.79a4.5 4.5 0 1 1 0 9Z"/><path d="M9 18v2M12 17v3M15 18v2"/>';
    } else if (c >= 95) {
      body = '<path d="M17.5 16H9a7 7 0 1 1 6.71-9h1.79a4.5 4.5 0 1 1 0 9Z"/><path d="M13 14l-3 5h3l-2 4"/>';
    } else if (c >= 51) {
      body = '<path d="M17.5 15H9a7 7 0 1 1 6.71-9h1.79a4.5 4.5 0 1 1 0 9Z"/><path d="M9 18v3M12 17v4M15 18v3"/>';
    } else {
      body = '<path d="M17.5 19H9a7 7 0 1 1 6.71-9h1.79a4.5 4.5 0 1 1 0 9Z"/>';
    }
    return '<svg class="' + cls + '" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">' + body + '</svg>';
  }
  function loadWeather() {
    const src = document.getElementById("weatherSource");
    fetch("weather.php", { cache: "no-store" }).then((r) => r.json()).then((d) => {
      if (!d.ok) {
        src.textContent = "Weather unavailable";
        return;
      }
      document.getElementById("weatherPlace").textContent = d.place;
      document.getElementById("weatherNow").textContent = d.now;
      document.getElementById("weatherSky").textContent = d.sky;
      document.getElementById("weatherWind").textContent = d.wind;
      document.getElementById("weatherNowIcon").innerHTML = wxIcon(d.code, "wx-icon-lg");
      src.textContent = d.source;
      const home = document.getElementById("homeOutside");
      if (home) home.textContent = d.now;
      const days = document.getElementById("weatherDays");
      days.innerHTML = (d.days || []).map((day) =>
        "<div class=\"col\"><div class=\"card-panel p-3 text-center h-100\">"
        + "<div class=\"muted small\">" + day.d + "</div>"
        + wxIcon(day.code)
        + "<div class=\"mt-1\">" + day.t + "</div>"
        + "<div class=\"muted small\">" + day.s + "</div></div></div>"
      ).join("");
    }).catch(() => { src.textContent = "Weather unavailable"; });
  }
  loadWeather();
</script>
</body>
</html>
