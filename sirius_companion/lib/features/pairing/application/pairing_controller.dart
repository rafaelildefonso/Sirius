import 'dart:async';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../../../core/network/api_client.dart' as api;
import '../../../core/device_identity.dart';

final pairingControllerProvider = StateNotifierProvider<PairingController, PairingState>((ref) {
  return PairingController();
});

class PairingState {
  final PairingStatus status;
  final String? message;
  final String? qrCodeData;
  final String? deviceToken;

  PairingState({
    this.status = PairingStatus.initial,
    this.message,
    this.qrCodeData,
    this.deviceToken,
  });

  PairingState copyWith({
    PairingStatus? status,
    String? message,
    String? qrCodeData,
    String? deviceToken,
  }) {
    return PairingState(
      status: status ?? this.status,
      message: message ?? this.message,
      qrCodeData: qrCodeData ?? this.qrCodeData,
      deviceToken: deviceToken ?? this.deviceToken,
    );
  }
}

enum PairingStatus {
  initial,
  scanning,
  connecting,
  pendingApproval,
  paired,
  error,
}

class PairingController extends StateNotifier<PairingState> {
  final api.ApiClient _apiClient = api.ApiClient.instance;

  PairingController() : super(PairingState());

  Future<void> startQrScan() async {
    state = state.copyWith(
      status: PairingStatus.scanning,
      message: 'Aponte a câmera para o QR code no PC',
    );
  }

  Future<void> processQrCode(String qrData) async {
    try {
      final uri = Uri.parse(qrData);
      final key = uri.queryParameters['key'];

      if (key == null || key.length != 6) {
        state = state.copyWith(
          status: PairingStatus.error,
          message: 'QR code inválido. Use o QR code do SIRIUS.',
        );
        return;
      }

      // The QR carries the PC origin (scheme://host:port). Persist and apply
      // it BEFORE pairing so every request targets the right server instead
      // of the hardcoded default.
      await DeviceIdentity.saveServerUrl(uri.origin);
      _apiClient.setBaseUrl(uri.origin);

      state = state.copyWith(
        status: PairingStatus.connecting,
        message: 'Conectando...',
        qrCodeData: qrData,
      );

      await _completePairingWithKey(key);
    } catch (_) {
      state = state.copyWith(
        status: PairingStatus.error,
        message: 'QR code inválido',
      );
    }
  }

  Future<void> _completePairingWithKey(String key) async {
    try {
      final deviceName = await DeviceIdentity.getDeviceName();
      final pairResult =
          await _apiClient.pairDevice(deviceName: deviceName, pairKey: key);

      if (pairResult.success) {
        state = state.copyWith(
          status: PairingStatus.paired,
          message: 'Pareado com sucesso!',
          deviceToken: pairResult.token,
        );
      } else if (pairResult.pendingApproval) {
        // Key expired between QR scan and pairing: fall back to approval flow.
        await _waitForApproval(pairResult.nonce, pairResult.message);
      } else {
        state = state.copyWith(
          status: PairingStatus.error,
          message: pairResult.error ?? 'Falha no pareamento',
        );
      }
    } catch (e) {
      state = state.copyWith(
        status: PairingStatus.error,
        message: 'Erro: $e',
      );
    }
  }

  Future<void> pairManually(String deviceName) async {
    state = state.copyWith(
      status: PairingStatus.connecting,
      message: 'Solicitando pareamento...',
    );

    try {
      final result = await _apiClient.pairDevice(deviceName: deviceName);

      if (result.success) {
        state = state.copyWith(
          status: PairingStatus.paired,
          message: 'Pareado com sucesso!',
          deviceToken: result.token,
        );
      } else if (result.pendingApproval) {
        await _waitForApproval(result.nonce, result.message);
      } else {
        state = state.copyWith(
          status: PairingStatus.error,
          message: result.error ?? 'Falha no pareamento',
        );
      }
    } catch (e) {
      state = state.copyWith(
        status: PairingStatus.error,
        message: 'Erro: $e',
      );
    }
  }

  /// Polls /api/device/pair/status while waiting for PC-side approval.
  Future<void> _waitForApproval(String? nonce, String? message) async {
    state = state.copyWith(
      status: PairingStatus.pendingApproval,
      message: message ?? 'Aguardando aprovação no PC...',
    );

    Timer.periodic(const Duration(seconds: 3), (timer) async {
      if (state.status != PairingStatus.pendingApproval) {
        timer.cancel();
        return;
      }
      final status = await _apiClient.checkPairingStatus(nonce: nonce);
      if (status == api.PairingStatus.paired) {
        timer.cancel();
        final token = await DeviceIdentity.getDeviceToken();
        state = state.copyWith(
          status: PairingStatus.paired,
          message: 'Pareado com sucesso!',
          deviceToken: token,
        );
      } else if (status == api.PairingStatus.rejected) {
        timer.cancel();
        state = state.copyWith(
          status: PairingStatus.error,
          message: 'Pareamento rejeitado no PC',
        );
      }
    });
  }
}

