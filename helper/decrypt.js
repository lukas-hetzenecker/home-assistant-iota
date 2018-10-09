var Mam = require('./lib/mam.client.js')

if (process.argv.length < 4) {
    console.error("node decrypt.js <payload> <root> [<sidekey>]");
    process.exit(1);
}

var payload = process.argv[2];
var root = process.argv[3];

var side_key = undefined;
if (process.argv.length > 4) {
    side_key = process.argv[4];
}

console.log(JSON.stringify(Mam.decode(payload, side_key, root)));
