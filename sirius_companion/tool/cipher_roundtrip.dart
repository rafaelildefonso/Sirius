// Round-trip cipher interop check against dashboard/server.py helpers.
// Usage: dart run tool/cipher_roundtrip.dart <python_encrypted_b64>
import 'dart:io';

import 'package:sirius_companion/core/crypto/aes_cipher.dart';

Future<void> main(List<String> args) async {
  const sessionKey = 'ABC234';
  final cipher = SiriusCipher(sessionKey);

  // Dart -> Python
  final enc = cipher.encryptJson({'text': 'ola do dart', 'n': 42});
  stdout.writeln(enc);

  // Python -> Dart
  if (args.isNotEmpty) {
    final dec = cipher.decryptJson(args[0]);
    if (dec == null || dec['text'] != 'segredo do python') {
      stderr.writeln('FAIL: could not decrypt python payload: $dec');
      exit(1);
    }
    stdout.writeln('PY_DECRYPT_OK');
  }
}
