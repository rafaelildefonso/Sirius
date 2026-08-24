import 'dart:async';
import 'package:dio/dio.dart';
import 'package:connectivity_plus/connectivity_plus.dart';
import 'package:package_info_plus/package_info_plus.dart';
import 'package:device_info_plus/device_info_plus.dart';
import '../config/constants.dart';
import '../device_identity.dart';

class ApiClient {
  static ApiClient? _instance;
  static ApiClient get instance => _instance ??= ApiClient._();
  
  late final Dio _dio;
  String _baseUrl = AppConstants.defaultBaseUrl;
  String? _deviceToken;
  final Connectivity _connectivity = Connectivity();
  PackageInfo? _packageInfo;
  AndroidDeviceInfo? _androidInfo;
  
  ApiClient._() {
    _dio = Dio(BaseOptions(
      baseUrl: _baseUrl,
      connectTimeout: const Duration(seconds: 10),
      receiveTimeout: const Duration(seconds: 30),
      sendTimeout: const Duration(seconds: 30),
      validateStatus: (status) => true,
      headers: {
        'Content-Type': 'application/json',
        'Accept': 'application/json',
      },
    ));
    
    _setupInterceptors();
    _initDeviceInfo();
  }
  
  Future<void> _initDeviceInfo() async {
    _packageInfo = await PackageInfo.fromPlatform();
    final deviceInfo = DeviceInfoPlugin();
    _androidInfo = await deviceInfo.androidInfo;
  }
  
  void _setupInterceptors() {
    // Request interceptor - add headers
    _dio.interceptors.add(InterceptorsWrapper(
      onRequest: (options, handler) async {
        // Add device ID to all requests
        final deviceId = await DeviceIdentity.getOrCreateId();
        options.headers['X-Device-ID'] = deviceId;
        
        // Add device token if paired
        if (_deviceToken != null) {
          options.headers['Authorization'] = 'Bearer $_deviceToken';
        } else {
          final token = await DeviceIdentity.getDeviceToken();
          if (token != null) {
            _deviceToken = token;
            options.headers['Authorization'] = 'Bearer $token';
          }
        }
        
        // App info headers
        if (_packageInfo != null) {
          options.headers['X-App-Version'] = _packageInfo!.version;
          options.headers['X-App-Build'] = _packageInfo!.buildNumber;
        }
        options.headers['X-Platform'] = 'android';
        if (_androidInfo != null) {
          options.headers['X-Device-Model'] = _androidInfo!.model;
          options.headers['X-Android-Version'] = _androidInfo!.version.release;
        }
        
        handler.next(options);
      },
      onError: (error, handler) async {
        // Handle 401 - token expired, clear and retry once
        if (error.response?.statusCode == 401 && 
            error.requestOptions.extra['retry'] != true) {
          
          await DeviceIdentity.clearPairing();
          _deviceToken = null;
          
          // Retry once without token
          final opts = Options(
            method: error.requestOptions.method,
            headers: error.requestOptions.headers,
            extra: {'retry': true},
          );
          
          try {
            final response = await _dio.request(
              error.requestOptions.path,
              data: error.requestOptions.data,
              queryParameters: error.requestOptions.queryParameters,
              options: opts,
            );
            handler.resolve(response);
            return;
          } catch (_) {
            // Fall through to error
          }
        }
        handler.next(error);
      },
    ));
    
    // Logging interceptor
    _dio.interceptors.add(LogInterceptor(
      request: true,
      requestHeader: true,
      requestBody: true,
      responseHeader: true,
      responseBody: true,
      error: true,
    ));
  }
  
  void setBaseUrl(String url) {
    _baseUrl = url;
    _dio.options.baseUrl = url;
  }

  /// Applies the PC URL persisted during QR pairing. Call once at app boot,
  /// before any request goes out; keeps the hardcoded default when absent.
  Future<void> restoreSavedBaseUrl() async {
    final saved = await DeviceIdentity.getServerUrl();
    if (saved != null && saved != _baseUrl) {
      setBaseUrl(saved);
    }
  }
  
  void setDeviceToken(String token) {
    _deviceToken = token;
  }
  
  void clearDeviceToken() {
    _deviceToken = null;
  }
  
  Dio get dio => _dio;
  
  // Convenience methods
  Future<Response> get(String path, {Map<String, dynamic>? queryParameters}) {
    return _dio.get(path, queryParameters: queryParameters);
  }
  
  Future<Response> post(String path, {dynamic data, Map<String, dynamic>? queryParameters}) {
    return _dio.post(path, data: data, queryParameters: queryParameters);
  }
  
  Future<Response> put(String path, {dynamic data}) {
    return _dio.put(path, data: data);
  }
  
  Future<Response> delete(String path) {
    return _dio.delete(path);
  }
  
  /// Check network connectivity
  Future<bool> hasConnection() async {
    final result = await _connectivity.checkConnectivity();
    return result != ConnectivityResult.none;
  }
  
  /// Check if server is reachable
  Future<bool> checkServerReachable() async {
    try {
      final response = await _dio.get(
        '/api/device/ping',
        options: Options(
          sendTimeout: Duration(seconds: 5),
          receiveTimeout: Duration(seconds: 5),
        ),
      );
      return response.statusCode == 200 && response.data['ok'] == true;
    } catch (_) {
      return false;
    }
  }
  
  /// Pair with Sirius PC
  Future<PairingResult> pairDevice({
    required String deviceName,
    String? qrCodeData,
  }) async {
    final deviceId = await DeviceIdentity.getOrCreateId();
    final platform = _androidInfo?.model ?? 'Android';
    final androidVersion = _androidInfo?.version.release ?? 'Unknown';
    
    final response = await _dio.post(
      '/api/device/pair',
      data: {
        'device_id': deviceId,
        'device_name': deviceName,
        'platform': 'android',
        'platform_version': androidVersion,
        'app_version': _packageInfo?.version ?? '1.0.0',
        'model': platform,
      },
    );
    
    if (response.statusCode == 200 && response.data['ok'] == true) {
      if (response.data['paired'] == true) {
        final token = response.data['device_token'] as String?;
        if (token != null) {
          await DeviceIdentity.savePairing(
            deviceToken: token,
            serverDeviceId: deviceId,
          );
          _deviceToken = token;
        }
        return PairingResult.success(token: token);
      } else if (response.data['pending_approval'] == true) {
        return PairingResult.pendingApproval(message: response.data['message'] as String?);
      }
    } else if (response.statusCode == 409) {
      return PairingResult.pendingApproval(message: response.data['message'] as String?);
    }
    
    return PairingResult.error(message: response.data['error'] as String? ?? 'Pairing failed');
  }
  
  /// Pair using a code from QR
  Future<PairingResult> pairWithCode(String code) async {
    final deviceName = await DeviceIdentity.getDeviceName();
    
    // Try auto-login with the key
    final autoLoginResponse = await _dio.get('/auto-login', queryParameters: {'key': code});
    
    if (autoLoginResponse.statusCode == 200) {
      // Now call the pair endpoint
      return await pairDevice(deviceName: deviceName);
    }
    
    return PairingResult.error(message: 'Invalid or expired code');
  }
  
  /// Check pairing status (polling)
  Future<PairingStatus> checkPairingStatus() async {
    try {
      final response = await _dio.get('/api/device/pair/status');
      if (response.statusCode == 200) {
        final status = response.data['status'] as String?;
        switch (status) {
          case 'paired':
            final token = response.data['device_token'] as String?;
            if (token != null) {
              await DeviceIdentity.savePairing(
                deviceToken: token,
                serverDeviceId: await DeviceIdentity.getOrCreateId(),
              );
              _deviceToken = token;
            }
            return PairingStatus.paired;
          case 'pending':
            return PairingStatus.pending;
          case 'rejected':
            return PairingStatus.rejected;
          default:
            return PairingStatus.unknown;
        }
      }
    } catch (_) {}
    return PairingStatus.error;
  }
  
  /// Ping server (health check)
  Future<PingResult> ping() async {
    try {
      final response = await _dio.get(
        '/api/device/ping',
        options: Options(
          sendTimeout: Duration(seconds: 5),
          receiveTimeout: Duration(seconds: 5),
        ),
      );
      
      if (response.statusCode == 200 && response.data['ok'] == true) {
        return PingResult(
          success: true,
          status: response.data['status'] as String?,
          serverTime: response.data['server_time'] as String?,
        );
      }
    } catch (e) {
      return PingResult(success: false, error: e.toString());
    }
    return PingResult(success: false, error: 'Unexpected response');
  }
  
  /// Sync batch of items to server
  Future<SyncResult> syncBatch(List<SyncBatchItem> items) async {
    if (items.isEmpty) return SyncResult.success(processed: 0);
    
    final deviceId = await DeviceIdentity.getOrCreateId();
    final payload = {
      'device_id': deviceId,
      'items': items.map((e) => e.toJson()).toList(),
    };
    
    try {
      final response = await _dio.post('/api/sync/batch', data: payload);
      
      if (response.statusCode == 200 && response.data['ok'] == true) {
        final processed = response.data['processed'] as int? ?? 0;
        final results = (response.data['results'] as List?)
            ?.map((r) => SyncItemResult.fromJson(r as Map<String, dynamic>))
            .toList() ?? [];
        
        return SyncResult.success(processed: processed, results: results);
      }
    } catch (e) {
      return SyncResult.error(error: e.toString());
    }
    return SyncResult.error(error: 'Unexpected response');
  }
  
  /// Pull new commands/tasks from server
  Future<PullResult> pullUpdates() async {
    try {
      final response = await _dio.get('/api/device/sync/pull');
      
      if (response.statusCode == 200 && response.data['ok'] == true) {
        return PullResult(
          success: true,
          commands: (response.data['commands'] as List?)?.map((c) => c as Map<String, dynamic>).toList() ?? [],
          places: (response.data['places'] as List?)?.map((p) => p as Map<String, dynamic>).toList() ?? [],
          tasks: (response.data['tasks'] as List?)?.map((t) => Map<String, dynamic>.from(t as Map)).toList() ?? [],
        );
      }
    } catch (e) {
      return PullResult(success: false, error: e.toString());
    }
    return PullResult(success: false, error: 'Unexpected response');
  }
}

// Result classes
class PairingResult {
  final bool success;
  final bool pendingApproval;
  final String? token;
  final String? message;
  final String? error;
  
  PairingResult._({
    required this.success,
    this.pendingApproval = false,
    this.token,
    this.message,
    this.error,
  });
  
  factory PairingResult.success({String? token}) = _PairingSuccess;
  factory PairingResult.pendingApproval({String? message}) = _PairingPending;
  factory PairingResult.error({String? message}) = _PairingError;
}

class _PairingSuccess extends PairingResult {
  _PairingSuccess({String? token}) : super._(success: true, token: token);
}

class _PairingPending extends PairingResult {
  _PairingPending({String? message}) : super._(success: false, pendingApproval: true, message: message);
}

class _PairingError extends PairingResult {
  _PairingError({String? message}) : super._(success: false, error: message);
}

enum PairingStatus { unknown, pending, paired, rejected, error }

class PingResult {
  final bool success;
  final String? status;
  final String? serverTime;
  final String? error;
  
  PingResult({
    required this.success,
    this.status,
    this.serverTime,
    this.error,
  });
}

class SyncBatchItem {
  final String clientId;
  final String type; // 'command', 'location_log', 'place_confirmation'
  final Map<String, dynamic> payload;
  
  SyncBatchItem({
    required this.clientId,
    required this.type,
    required this.payload,
  });
  
  Map<String, dynamic> toJson() => {
    'client_id': clientId,
    'type': type,
    'payload': payload,
  };
}

class SyncResult {
  final bool success;
  final int processed;
  final List<SyncItemResult> results;
  final String? error;
  
  SyncResult._({
    required this.success,
    this.processed = 0,
    this.results = const [],
    this.error,
  });
  
  factory SyncResult.success({required int processed, List<SyncItemResult>? results}) = _SyncSuccess;
  factory SyncResult.error({String? error}) = _SyncError;
}

class _SyncSuccess extends SyncResult {
  _SyncSuccess({required int processed, List<SyncItemResult>? results}) 
    : super._(success: true, processed: processed, results: results ?? []);
}

class _SyncError extends SyncResult {
  _SyncError({String? error}) : super._(success: false, error: error);
}

class SyncItemResult {
  final String clientId;
  final String status; // 'processed', 'failed'
  final String? serverId;
  final String? error;
  
  SyncItemResult({
    required this.clientId,
    required this.status,
    this.serverId,
    this.error,
  });
  
  factory SyncItemResult.fromJson(Map<String, dynamic> json) {
    return SyncItemResult(
      clientId: json['client_id'] as String,
      status: json['status'] as String,
      serverId: json['server_id'] as String?,
      error: json['error'] as String?,
    );
  }
}

class PullResult {
  final bool success;
  final List<Map<String, dynamic>> commands;
  final List<Map<String, dynamic>> places;
  final List<Map<String, dynamic>> tasks;
  final String? error;
  
  PullResult({
    required this.success,
    this.commands = const [],
    this.places = const [],
    this.tasks = const [],
    this.error,
  });
}