import 'dart:convert';
import 'dart:typed_data';

import 'package:crypto/crypto.dart';
import 'package:encrypt/encrypt.dart' as encrypt;

/// AES-256-CBC cipher compatible with the dashboard's scheme
/// (see `dashboard/server.py::_derive_key`):
///
/// - key     = SHA-256(sessionKey || 'SIRIUS-DASHBOARD-v1')
/// - payload = base64(IV[16] || ciphertext), PKCS7 padding
class SiriusCipher {
  SiriusCipher(String sessionKey) : _key = _derive(sessionKey);

  static const String salt = 'SIRIUS-DASHBOARD-v1';

  final Uint8List _key;

  static Uint8List _derive(String sessionKey) {
    final digest = sha256.convert(utf8.encode(sessionKey + salt));
    return Uint8List.fromList(digest.bytes);
  }

  encrypt.Encrypter get _encrypter => encrypt.Encrypter(
        encrypt.AES(encrypt.Key(_key), mode: encrypt.AESMode.cbc),
      );

  /// Encrypt a JSON-encodable map into base64(IV || ciphertext).
  String encryptJson(Map<String, dynamic> data) =>
      encryptText(jsonEncode(data));

  /// Decrypt base64(IV || ciphertext) back into a map (null on failure).
  Map<String, dynamic>? decryptJson(String encB64) {
    final raw = decryptText(encB64);
    if (raw == null) return null;
    try {
      final decoded = jsonDecode(raw);
      return decoded is Map<String, dynamic> ? decoded : null;
    } catch (_) {
      return null;
    }
  }

  String encryptText(String plaintext) {
    final iv = encrypt.IV.fromSecureRandom(16);
    final encrypted = _encrypter.encrypt(plaintext, iv: iv);
    return base64Encode([...iv.bytes, ...encrypted.bytes]);
  }

  String? decryptText(String encB64) {
    try {
      final raw = base64Decode(encB64);
      if (raw.length <= 16) return null;
      final iv = encrypt.IV(Uint8List.fromList(raw.sublist(0, 16)));
      final data =
          encrypt.Encrypted(Uint8List.fromList(raw.sublist(16)));
      return _encrypter.decrypt(data, iv: iv);
    } catch (_) {
      return null;
    }
  }
}
