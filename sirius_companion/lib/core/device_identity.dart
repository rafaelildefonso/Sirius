import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:uuid/uuid.dart';

class DeviceIdentity {

  static bool? _testPairedOverride;
  static void setTestPaired(bool value) {
    _testPairedOverride = value;
  }

  static const _storage = FlutterSecureStorage(
    aOptions: AndroidOptions(
      encryptedSharedPreferences: true,
    ),
  );
  
  static const _keyDeviceId = 'sirius_device_id';
  static const _keyDeviceName = 'sirius_device_name';
  static const _keyPairedDeviceToken = 'sirius_paired_device_token';
  static const _keyPairedDeviceId = 'sirius_paired_device_id';
  static const _keyPairedAt = 'sirius_paired_at';
  
  /// Get or create the unique device ID (persists in Keystore/Keychain)
  static Future<String> getOrCreateId() async {
    String? existing = await _storage.read(key: _keyDeviceId);
    if (existing != null && existing.isNotEmpty) {
      return existing;
    }
    
    final newId = Uuid().v4();
    await _storage.write(key: _keyDeviceId, value: newId);
    return newId;
  }
  
  /// Get the device name (defaults to model name)
  static Future<String> getDeviceName() async {
    String? name = await _storage.read(key: _keyDeviceName);
    if (name != null && name.isNotEmpty) return name;
    
    // Try to get device model
    try {
      // This would need device_info_plus package
      // For now, return generic
      name = 'Android Device';
    } catch (_) {
      name = 'Android Device';
    }
    
    await _storage.write(key: _keyDeviceName, value: name);
    return name;
  }
  
  /// Set custom device name
  static Future<void> setDeviceName(String name) async {
    await _storage.write(key: _keyDeviceName, value: name);
  }
  
  /// Save pairing credentials
  static Future<void> savePairing({
    required String deviceToken,
    required String serverDeviceId,
  }) async {
    await _storage.write(key: _keyPairedDeviceToken, value: deviceToken);
    await _storage.write(key: _keyPairedDeviceId, value: serverDeviceId);
    await _storage.write(key: _keyPairedAt, value: DateTime.now().toIso8601String());
  }
  
  /// Get stored device token for authenticated requests
  static Future<String?> getDeviceToken() async {
    return await _storage.read(key: _keyPairedDeviceToken);
  }
  
  /// Get paired server device ID
  static Future<String?> getPairedDeviceId() async {
    return await _storage.read(key: _keyPairedDeviceId);
  }
  
  /// Check if device is paired
  static Future<bool> isPaired() async {
    if (_testPairedOverride != null) {
      return _testPairedOverride!;
    }
    final token = await getDeviceToken();
    return token != null && token.isNotEmpty;
  }
  
  /// Get pairing timestamp
  static Future<DateTime?> getPairedAt() async {
    final str = await _storage.read(key: _keyPairedAt);
    if (str != null) {
      try {
        return DateTime.parse(str);
      } catch (_) {}
    }
    return null;
  }
  
  /// Clear pairing (unpair)
  static Future<void> clearPairing() async {
    await _storage.delete(key: _keyPairedDeviceToken);
    await _storage.delete(key: _keyPairedDeviceId);
    await _storage.delete(key: _keyPairedAt);
  }
  
  /// Clear everything (factory reset)
  static Future<void> clearAll() async {
    await _storage.deleteAll();
  }
}