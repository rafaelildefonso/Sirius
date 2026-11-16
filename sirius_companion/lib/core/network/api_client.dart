import 'dart:async';
import 'dart:io';

import 'package:dio/dio.dart';
import 'package:connectivity_plus/connectivity_plus.dart';
import 'package:flutter/foundation.dart' show debugPrint;
import 'package:package_info_plus/package_info_plus.dart';
import 'package:device_info_plus/device_info_plus.dart';
import '../config/constants.dart';
import '../crypto/aes_cipher.dart';
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
    _dio = Dio(
      BaseOptions(
        baseUrl: _baseUrl,
        connectTimeout: const Duration(seconds: 10),
        receiveTimeout: const Duration(seconds: 30),
        sendTimeout: const Duration(seconds: 30),
        validateStatus: (status) => true,
        headers: {
          'Content-Type': 'application/json',
          'Accept': 'application/json',
        },
      ),
    );

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
    _dio.interceptors.add(
      InterceptorsWrapper(
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
            options.headers['X-Android-Version'] =
                _androidInfo!.version.release;
          }

          handler.next(options);
        },
        onError: (error, handler) async {
          // Handle 401 - token expired, clear token and retry once WITHOUT clearing pairing
          if (error.response?.statusCode == 401 &&
              error.requestOptions.extra['retry'] != true) {
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
      ),
    );

    // Logging interceptor
    _dio.interceptors.add(
      LogInterceptor(
        request: true,
        requestHeader: true,
        requestBody: true,
        responseHeader: true,
        responseBody: true,
        error: true,
      ),
    );
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

  Future<Response> post(
    String path, {
    dynamic data,
    Map<String, dynamic>? queryParameters,
  }) {
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
    return result.any((connection) => connection != ConnectivityResult.none);
  }

  /// Check if server is reachable
  Future<bool> checkServerReachable() async {
    try {
      final response = await _dio.get(
        '/api/device/ping',
        options: Options(
          connectTimeout: const Duration(seconds: 2),
          sendTimeout: const Duration(seconds: 2),
          receiveTimeout: const Duration(seconds: 2),
        ),
      );
      return response.statusCode == 200 && response.data['ok'] == true;
    } on DioException {
      return false;
    }
  }

  /// Discover Sirius server on the local network via UDP broadcast.
  /// Returns the discovered base URL (e.g., "http://192.168.1.15:8000") or null if not found.
  Future<String?> discoverServerOnLan({bool checkSavedUrl = true}) async {
    final deviceId = await DeviceIdentity.getOrCreateId();
    final token = await DeviceIdentity.getDeviceToken();
    final probeHeaders = {
      'X-Device-ID': deviceId,
      if (token != null) 'Authorization': 'Bearer $token',
    };

    // 1. Try saved URL first
    final savedUrl = await DeviceIdentity.getServerUrl();
    if (checkSavedUrl && savedUrl != null) {
      if (await _probeServerAt(savedUrl, headers: probeHeaders)) {
        setBaseUrl(savedUrl);
        return savedUrl;
      }
    }

    // 2. Try UDP broadcast discovery
    final responses = <String>{};
    RawDatagramSocket? socket;
    StreamSubscription<RawSocketEvent>? subscription;
    try {
      final discoverySocket = await RawDatagramSocket.bind(
        InternetAddress.anyIPv4,
        0,
      );
      socket = discoverySocket;
      subscription = discoverySocket.listen((event) {
        if (event == RawSocketEvent.read) {
          final datagram = discoverySocket.receive();
          if (datagram != null) {
            final msg = String.fromCharCodes(datagram.data).trim();
            if (msg.startsWith('SIRIUS_ANNOUNCE:')) {
              final url = msg.substring('SIRIUS_ANNOUNCE:'.length);
              responses.add(url);
            }
          }
        }
      });

      // Send discovery ping
      final broadcastAddr = InternetAddress('255.255.255.255');
      discoverySocket.send(
        'SIRIUS_DISCOVERY_PING'.codeUnits,
        broadcastAddr,
        8002,
      );

      await Future.delayed(const Duration(milliseconds: 1200));
    } on SocketException catch (e) {
      debugPrint('[ApiClient] UDP discovery failed: $e');
    } finally {
      await subscription?.cancel();
      socket?.close();
    }

    for (final url in responses) {
      if (await _probeServerAt(url, headers: probeHeaders)) {
        await DeviceIdentity.saveServerUrl(url);
        setBaseUrl(url);
        return url;
      }
    }

    // UDP discovery is not available on some Wi-Fi networks. Fall back to a
    // bounded, concurrent scan instead of waiting on every address in series.
    final localIp = await _getLocalIp();
    if (localIp != null) {
      final parts = localIp.split('.');
      final ownHost = int.tryParse(parts.last);
      if (parts.length == 4 && ownHost != null) {
        final subnet = '${parts[0]}.${parts[1]}.${parts[2]}';
        const batchSize = 32;
        const probeTimeout = Duration(milliseconds: 500);
        for (var start = 1; start < 255; start += batchSize) {
          final hosts = [
            for (
              var host = start;
              host < start + batchSize && host < 255;
              host++
            )
              if (host != ownHost) host,
          ];
          final urls = hosts.map((host) => 'http://$subnet.$host:8000');
          final results = await Future.wait(
            urls.map(
              (url) => _probeServerAt(
                url,
                headers: probeHeaders,
                timeout: probeTimeout,
              ),
            ),
          );
          final matchIndex = results.indexOf(true);
          if (matchIndex != -1) {
            final url = urls.elementAt(matchIndex);
            await DeviceIdentity.saveServerUrl(url);
            setBaseUrl(url);
            return url;
          }
        }
      }
    }

    return null;
  }

  Future<bool> _probeServerAt(
    String url, {
    required Map<String, String> headers,
    Duration timeout = const Duration(seconds: 2),
  }) async {
    final uri = Uri.tryParse(url);
    if (uri == null || uri.scheme != 'http' || uri.host.isEmpty) return false;

    final probe = Dio(
      BaseOptions(
        baseUrl: url,
        connectTimeout: timeout,
        sendTimeout: timeout,
        receiveTimeout: timeout,
        headers: headers,
      ),
    );
    try {
      final response = await probe.get('/api/device/ping');
      return response.statusCode == 200 &&
          response.data is Map &&
          response.data['ok'] == true;
    } on DioException {
      return false;
    } on FormatException {
      return false;
    } finally {
      probe.close(force: true);
    }
  }

  Future<String?> _getLocalIp() async {
    try {
      final interfaces = await NetworkInterface.list(
        includeLoopback: false,
        type: InternetAddressType.IPv4,
      );
      for (final interface in interfaces) {
        for (final addr in interface.addresses) {
          final octets = addr.address.split('.').map(int.tryParse).toList();
          if (octets.length != 4 || octets.any((part) => part == null)) {
            continue;
          }
          final first = octets[0]!;
          final second = octets[1]!;
          final isPrivate =
              first == 10 ||
              (first == 172 && second >= 16 && second <= 31) ||
              (first == 192 && second == 168);
          if (isPrivate) return addr.address;
        }
      }
    } on SocketException catch (e) {
      debugPrint('[ApiClient] Could not inspect local network interfaces: $e');
    }
    return null;
  }

  /// Pair with Sirius PC.
  ///
  /// [pairKey] is the one-time code from the PC's QR code — when valid, the
  /// server auto-approves. Without it the device goes to pending approval
  /// (HTTP 409) until someone approves on the PC.
  Future<PairingResult> pairDevice({
    required String deviceName,
    String? pairKey,
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
        if (pairKey != null && pairKey.isNotEmpty) 'pair_key': pairKey,
      },
    );

    if (response.statusCode == 200 && response.data['ok'] == true) {
      if (response.data['paired'] == true) {
        final token = response.data['device_token'] as String?;
        final sessionKey = response.data['session_key'] as String?;
        if (token != null) {
          await DeviceIdentity.savePairing(
            deviceToken: token,
            serverDeviceId: deviceId,
            sessionKey: sessionKey,
          );
          _deviceToken = token;
        }
        return PairingResult.success(token: token);
      } else if (response.data['pending_approval'] == true) {
        return PairingResult.pendingApproval(
          message: response.data['message'] as String?,
        );
      }
    } else if (response.statusCode == 409) {
      return PairingResult.pendingApproval(
        message: response.data['message'] as String?,
        nonce: response.data['nonce'] as String?,
      );
    } else if (response.statusCode == 401) {
      return PairingResult.error(
        message:
            response.data['error'] as String? ?? 'Código inválido ou expirado',
      );
    }

    return PairingResult.error(
      message: response.data['error'] as String? ?? 'Pairing failed',
    );
  }

  /// Check pairing status (polling while pending approval).
  /// [nonce] proves this device originated the pair request.
  Future<PairingStatus> checkPairingStatus({String? nonce}) async {
    try {
      final deviceId = await DeviceIdentity.getOrCreateId();
      final response = await _dio.get(
        '/api/device/pair/status',
        queryParameters: {
          'device_id': deviceId,
          if (nonce != null && nonce.isNotEmpty) 'nonce': nonce,
        },
      );
      if (response.statusCode == 200) {
        final status = response.data['status'] as String?;
        switch (status) {
          case 'paired':
            final token = response.data['device_token'] as String?;
            if (token != null) {
              await DeviceIdentity.savePairing(
                deviceToken: token,
                serverDeviceId: deviceId,
                sessionKey: response.data['session_key'] as String?,
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

  /// Requests PC shutdown directly from the paired-device endpoint.
  /// The server never sends this request through the assistant/model queue.
  Future<ComputerShutdownResult> requestComputerShutdown() async {
    try {
      final response = await _dio.post('/api/device/shutdown');
      final data = response.data is Map
          ? Map<String, dynamic>.from(response.data as Map)
          : <String, dynamic>{};
      if (response.statusCode == 200 && data['ok'] == true) {
        final status = data['status'] as String?;
        if (status == 'accepted' || status == 'already_requested') {
          return ComputerShutdownResult.accepted(
            alreadyRequested: status == 'already_requested',
          );
        }
      }
      if (response.statusCode == 401 || response.statusCode == 403) {
        return ComputerShutdownResult.rejected(
          'Este celular não está autorizado pelo PC pareado.',
        );
      }
      return ComputerShutdownResult.failed(
        data['error']?.toString() ?? 'O PC recusou o pedido de desligamento.',
      );
    } on DioException {
      return ComputerShutdownResult.unavailable(
        'Não foi possível alcançar o PC. Ele pode estar desconectado ou indisponível.',
      );
    } catch (_) {
      return ComputerShutdownResult.unavailable(
        'Não foi possível confirmar a resposta do PC. Verifique a conexão.',
      );
    }
  }

  /// Sync batch of items to server.
  ///
  /// When a session key was issued at pairing time, every item payload is
  /// AES-256-CBC encrypted (`"enc": true`, base64 IV||ciphertext).
  Future<SyncResult> syncBatch(
    List<SyncBatchItem> items, {
    bool announceToPc = false,
  }) async {
    if (items.isEmpty) return SyncResult.success(processed: 0);

    final deviceId = await DeviceIdentity.getOrCreateId();
    final cipher = await _cipher();

    final payload = {
      'device_id': deviceId,
      'items': items.map((item) {
        final json = item.toJson();
        if (cipher != null) {
          return {
            'client_id': json['client_id'],
            'type': json['type'],
            'payload': cipher.encryptJson(
              json['payload'] as Map<String, dynamic>,
            ),
            'enc': true,
          };
        }
        return json;
      }).toList(),
    };

    try {
      final response = await _dio.post(
        '/api/sync/batch',
        data: payload,
        options: Options(
          headers: {'X-Sync-Announce': announceToPc ? 'true' : 'false'},
        ),
      );

      if (response.statusCode == 200 && response.data['ok'] == true) {
        final processed = response.data['processed'] as int? ?? 0;
        final results =
            (response.data['results'] as List?)
                ?.map((r) => SyncItemResult.fromJson(r as Map<String, dynamic>))
                .toList() ??
            [];

        return SyncResult.success(processed: processed, results: results);
      }
    } catch (e) {
      return SyncResult.error(error: e.toString());
    }
    return SyncResult.error(error: 'Unexpected response');
  }

  /// Pull new commands/tasks and mobile-owned recurring definitions from server.
  ///
  /// Items arrive encrypted when the device has a session key; they are
  /// transparently decrypted here so callers always see plain maps.
  Future<PullResult> pullUpdates() async {
    try {
      final response = await _dio.get('/api/device/sync/pull');

      if (response.statusCode == 200 && response.data['ok'] == true) {
        final encrypted = response.data['enc'] == true;
        final cipher = encrypted ? await _cipher() : null;

        List<Map<String, dynamic>> decodeList(dynamic list) {
          return (list as List?)
                  ?.map((entry) {
                    final map = entry as Map<String, dynamic>;
                    if (encrypted && map['enc'] == true && cipher != null) {
                      return cipher.decryptJson(map['payload'] as String);
                    }
                    return Map<String, dynamic>.from(map);
                  })
                  .whereType<Map<String, dynamic>>()
                  .toList() ??
              [];
        }

        return PullResult(
          success: true,
          commands: decodeList(response.data['commands']),
          places:
              (response.data['places'] as List?)
                  ?.map((p) => p as Map<String, dynamic>)
                  .toList() ??
              [],
          tasks: decodeList(response.data['tasks']),
          recurring: decodeList(response.data['recurring']),
        );
      }
    } catch (e) {
      return PullResult(success: false, error: e.toString());
    }
    return PullResult(success: false, error: 'Unexpected response');
  }

  /// List recurring task definitions from the PC (plain JSON REST, like
  /// /api/tasks — the pull sync only covers generated instances).
  Future<List<Map<String, dynamic>>> getRecurringTasks() async {
    try {
      final response = await _dio.get('/api/recurring');
      if (response.statusCode == 200 && response.data['ok'] == true) {
        return (response.data['recurring'] as List? ?? [])
            .whereType<Map>()
            .map((e) => Map<String, dynamic>.from(e as Map<String, dynamic>))
            .toList();
      }
    } catch (_) {}
    return [];
  }

  /// Create a recurring task definition on the PC. Returns (recurring, error):
  /// recurring is the stored definition when ok, error carries the message
  /// from the server (validation/app-down) on failure.
  Future<(Map<String, dynamic>?, String?)> createRecurringTask(
    Map<String, dynamic> payload,
  ) async {
    try {
      final response = await _dio.post('/api/recurring', data: payload);
      if (response.statusCode == 200 &&
          response.data['ok'] == true &&
          response.data['recurring'] is Map) {
        return (
          Map<String, dynamic>.from(response.data['recurring'] as Map),
          null,
        );
      }
      final err = response.data is Map ? response.data['error'] : null;
      return (null, err?.toString() ?? 'Erro ao criar recorrência');
    } catch (e) {
      return (null, 'Falha de conexão: $e');
    }
  }

  /// Partially update a recurring definition (enable/disable, config fields).
  Future<bool> updateRecurringTask(
    String id,
    Map<String, dynamic> payload,
  ) async {
    if (id.isEmpty) return false;
    try {
      final response = await _dio.patch('/api/recurring/$id', data: payload);
      return response.statusCode == 200 && response.data['ok'] == true;
    } catch (_) {
      return false;
    }
  }

  /// Delete a recurring definition (also drops its pending generated tasks).
  Future<bool> deleteRecurringTask(String id) async {
    if (id.isEmpty) return false;
    try {
      final response = await _dio.delete('/api/recurring/$id');
      return response.statusCode == 200 && response.data['ok'] == true;
    } catch (_) {
      return false;
    }
  }

  /// Cipher for the paired device's session key, or null when unpaired/legacy.
  SiriusCipher? _cachedCipher;
  String? _cachedSessionKey;
  Future<SiriusCipher?> _cipher() async {
    final sk = await DeviceIdentity.getSessionKey();
    if (sk == null) return null;
    if (_cachedCipher == null || _cachedSessionKey != sk) {
      _cachedCipher = SiriusCipher(sk);
      _cachedSessionKey = sk;
    }
    return _cachedCipher;
  }
}

// Result classes
class PairingResult {
  final bool success;
  final bool pendingApproval;
  final String? token;
  final String? message;
  final String? error;

  /// Proof-of-identity for pair/status polling while pending approval.
  final String? nonce;

  PairingResult._({
    required this.success,
    this.pendingApproval = false,
    this.token,
    this.message,
    this.error,
    this.nonce,
  });

  factory PairingResult.success({String? token}) = _PairingSuccess;
  factory PairingResult.pendingApproval({String? message, String? nonce}) =
      _PairingPending;
  factory PairingResult.error({String? message}) = _PairingError;
}

class _PairingSuccess extends PairingResult {
  _PairingSuccess({String? token}) : super._(success: true, token: token);
}

class _PairingPending extends PairingResult {
  _PairingPending({String? message, String? nonce})
    : super._(
        success: false,
        pendingApproval: true,
        message: message,
        nonce: nonce,
      );
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

  PingResult({required this.success, this.status, this.serverTime, this.error});
}

class ComputerShutdownResult {
  final bool accepted;
  final bool alreadyRequested;
  final bool unavailable;
  final String message;

  const ComputerShutdownResult._({
    required this.accepted,
    required this.alreadyRequested,
    required this.unavailable,
    required this.message,
  });

  factory ComputerShutdownResult.accepted({bool alreadyRequested = false}) =>
      ComputerShutdownResult._(
        accepted: true,
        alreadyRequested: alreadyRequested,
        unavailable: false,
        message: alreadyRequested
            ? 'O desligamento já havia sido solicitado.'
            : 'O PC aceitou o pedido de desligamento.',
      );

  factory ComputerShutdownResult.rejected(String message) =>
      ComputerShutdownResult._(
        accepted: false,
        alreadyRequested: false,
        unavailable: false,
        message: message,
      );

  factory ComputerShutdownResult.failed(String message) =>
      ComputerShutdownResult._(
        accepted: false,
        alreadyRequested: false,
        unavailable: false,
        message: message,
      );

  factory ComputerShutdownResult.unavailable(String message) =>
      ComputerShutdownResult._(
        accepted: false,
        alreadyRequested: false,
        unavailable: true,
        message: message,
      );
}

class SyncBatchItem {
  final String clientId;
  final String type; // 'command', 'place_confirmation', 'gemma_fallback', ...
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

  factory SyncResult.success({
    required int processed,
    List<SyncItemResult>? results,
  }) = _SyncSuccess;
  factory SyncResult.error({String? error}) = _SyncError;

  List<String> confirmedClientIds(List<String> submittedClientIds) {
    final confirmed = results
        .where(
          (result) =>
              result.status == 'processed' &&
              submittedClientIds.contains(result.clientId),
        )
        .map((result) => result.clientId)
        .toSet();

    // Older PC versions acknowledge only the total number processed, without
    // returning per-item results. The aggregate confirms the whole batch only
    // when it exactly matches its size.
    if (results.isEmpty && processed == submittedClientIds.length) {
      return submittedClientIds;
    }
    return confirmed.toList();
  }
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
  final List<Map<String, dynamic>> recurring;
  final String? error;

  PullResult({
    required this.success,
    this.commands = const [],
    this.places = const [],
    this.tasks = const [],
    this.recurring = const [],
    this.error,
  });
}
