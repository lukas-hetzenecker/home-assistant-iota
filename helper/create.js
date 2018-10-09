var Mam = require('./lib/mam.client.js')

if (process.argv.length < 4) {
    console.error("node decrypt.js <state> <message>");
    process.exit(1);
}

var state = JSON.parse(process.argv[2]);
var message = process.argv[3];

var msg = Mam.create(state, message);
console.log(JSON.stringify(msg));

