import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:sirius_companion/core/network/tcp_transfer_client.dart';

void main() {
  test('reads a fragmented ACK as a complete JSON line', () async {
    final server = await ServerSocket.bind(InternetAddress.loopbackIPv4, 0);
    final serverResponse = server.first.then((socket) async {
      final lines = StreamIterator<String>(
        socket
            .cast<List<int>>()
            .transform(utf8.decoder)
            .transform(const LineSplitter()),
      );
      expect(await lines.moveNext(), isTrue);
      expect(jsonDecode(lines.current)['version'], 1);
      expect(await lines.moveNext(), isTrue);
      expect(jsonDecode(lines.current)['uuid'], 'note-1');

      socket.add(utf8.encode('{"uuid":"note-1","ok":'));
      await socket.flush();
      await Future<void>.delayed(const Duration(milliseconds: 20));
      socket.add(utf8.encode('true,"result":{}}\n'));
      await socket.flush();

      await lines.cancel();
      await socket.close();
    });

    final client = TcpTransferClient();
    try {
      await client.connect('127.0.0.1', server.port);
      await client.sendHeader(
        sessionKey: 'session-key',
        deviceId: 'device-1',
        totalItems: 1,
        totalBytes: 0,
      );
      final result = await client.sendNote(
        TcpTransferItem(
          uuid: 'note-1',
          type: 'note',
          category: 'geral',
          title: 'Teste',
          content: 'Conteúdo',
          contentLength: 0,
        ),
      );

      await serverResponse;
      expect(result.ok, isTrue);
      expect(result.uuid, 'note-1');
    } finally {
      await client.disconnect();
      await server.close();
    }
  });
}
