const http = require('node:http');
http.createServer((_request, response) => response.end('lava-node-fixture\n')).listen(8000, '0.0.0.0');
