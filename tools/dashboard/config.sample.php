<?php
/**
 * Copy to config.php (gitignored) and fill in local URLs.
 * The sample dashboard renders without this file; cameras and IPTV stay empty.
 */
return [
    'cameras' => [
        // ['name' => 'Driveway', 'url' => 'http://camera.local/snapshot.jpg'],
    ],
    'iptv' => [
        // 'rtp1' => 'http://tvheadend.local:9981/stream/channelid/1?profile=pass',
    ],
    'xtream' => [
        // 'api' => 'http://xtream.local/iptv/player_api.php',
        // 'stream' => 'http://xtream.local',
        // 'username' => 'user',
        // 'password' => 'pass',
    ],
    'sip' => [
        // 'server' => '10.0.0.1',
        // 'user' => 'tablet',
        // 'password' => 'secret',
        // 'port' => 5060,
    ],
    'sip_contacts' => [
        // ['name' => 'Kitchen', 'number' => '101'],
    ],
];
