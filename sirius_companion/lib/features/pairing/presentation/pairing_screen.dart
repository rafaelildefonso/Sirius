import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:mobile_scanner/mobile_scanner.dart';
import '../application/pairing_controller.dart';
import '../../home/presentation/home_screen.dart';
import '../../home/application/home_controller.dart';

class PairingScreen extends ConsumerStatefulWidget {
  const PairingScreen({super.key});

  @override
  ConsumerState<PairingScreen> createState() => _PairingScreenState();
}

class _PairingScreenState extends ConsumerState<PairingScreen> {
  MobileScannerController? _scannerController;
  bool _isScanning = false;
  bool _showScanner = false;

  @override
  void dispose() {
    _scannerController?.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final state = ref.watch(pairingControllerProvider);
    final controller = ref.read(pairingControllerProvider.notifier);

    ref.listen(pairingControllerProvider, (_, next) {
      if (next.status == PairingStatus.paired) {
        // Update the reactive paired provider so the auth gate navigates to Home
        ref.read(isPairedProvider.notifier).state = true;
        Navigator.of(context).pushReplacement(
          MaterialPageRoute(builder: (_) => const HomeScreen()),
        );
      }
    });

    return Scaffold(
      backgroundColor: const Color(0xFF07090F),
      body: SafeArea(
        child: Padding(
          padding: const EdgeInsets.all(24),
          child: Column(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              // Logo
              const Text(
                'SIRIUS',
                style: TextStyle(
                  fontSize: 36,
                  fontWeight: FontWeight.w700,
                  letterSpacing: 12,
                  color: Colors.white,
                ),
              ),
              const SizedBox(height: 4),
              const Text(
                'Companion',
                style: TextStyle(
                  fontSize: 12,
                  color: Color(0xFF5E6A7E),
                  letterSpacing: 4,
                  fontWeight: FontWeight.w500,
                ),
              ),
              const SizedBox(height: 48),

              // Status Card
              Container(
                width: double.infinity,
                padding: const EdgeInsets.all(24),
                decoration: BoxDecoration(
                  color: const Color(0xFFFFFFFF).withOpacity(0.04),
                  border: Border.all(color: const Color(0xFFFFFFFF).withOpacity(0.08)),
                  borderRadius: BorderRadius.circular(22),
                ),
                child: Column(
                  children: [
                    _buildStatusIcon(state.status),
                    const SizedBox(height: 16),
                    Text(
                      _getStatusTitle(state.status),
                      style: const TextStyle(
                        fontSize: 18,
                        fontWeight: FontWeight.w600,
                        color: Colors.white,
                      ),
                    ),
                    const SizedBox(height: 8),
                    Text(
                      state.message ?? _getStatusMessage(state.status),
                      style: const TextStyle(
                        fontSize: 14,
                        color: Color(0xFF5E6A7E),
                        height: 1.5,
                      ),
                      textAlign: TextAlign.center,
                    ),

                    // QR Scanner
                    if (state.status == PairingStatus.scanning) ...[
                      const SizedBox(height: 24),
                      SizedBox(
                        width: 240,
                        height: 240,
                        child: ClipRRect(
                          borderRadius: BorderRadius.circular(16),
                          child: MobileScanner(
                            controller: _scannerController ??= MobileScannerController(
                              detectionSpeed: DetectionSpeed.noDuplicates,
                              facing: CameraFacing.back,
                            ),
                            onDetect: (capture) {
                              if (!_isScanning) {
                                _isScanning = true;
                                final barcodes = capture.barcodes;
                                for (final barcode in barcodes) {
                                  if (barcode.rawValue != null) {
                                    controller.processQrCode(barcode.rawValue!);
                                    break;
                                  }
                                }
                                Future.delayed(const Duration(seconds: 2), () {
                                  _isScanning = false;
                                });
                              }
                            },
                          ),
                        ),
                      ),
                      const SizedBox(height: 16),
                      const Text(
                        'Aponte a câmera para o QR code no PC',
                        style: TextStyle(fontSize: 12, color: Color(0xFF5E6A7E)),
                      ),
                    ],

                    // Pending approval spinner
                    if (state.status == PairingStatus.pendingApproval) ...[
                      const SizedBox(height: 24),
                      const CircularProgressIndicator(
                        valueColor: AlwaysStoppedAnimation(Color(0xFF6366F1)),
                      ),
                      const SizedBox(height: 12),
                      const Text(
                        'Verifique o PC e clique em "Confiar"',
                        style: TextStyle(fontSize: 12, color: Color(0xFF5E6A7E)),
                      ),
                    ],

                    // Success
                    if (state.status == PairingStatus.paired) ...[
                      const SizedBox(height: 24),
                      Container(
                        padding: const EdgeInsets.all(16),
                        decoration: BoxDecoration(
                          color: const Color(0xFF22C55E).withOpacity(0.1),
                          border: Border.all(color: const Color(0xFF22C55E).withOpacity(0.3)),
                          borderRadius: BorderRadius.circular(12),
                        ),
                        child: Row(
                          mainAxisAlignment: MainAxisAlignment.center,
                          children: [
                            const Icon(Icons.check_circle, color: Color(0xFF22C55E), size: 24),
                            const SizedBox(width: 12),
                            const Text(
                              'Pronto! Redirecionando...',
                              style: TextStyle(
                                color: Color(0xFF22C55E),
                                fontWeight: FontWeight.w600,
                                fontSize: 14,
                              ),
                            ),
                          ],
                        ),
                      ),
                    ],

                    // Error
                    if (state.status == PairingStatus.error) ...[
                      const SizedBox(height: 24),
                      Container(
                        padding: const EdgeInsets.all(16),
                        decoration: BoxDecoration(
                          color: const Color(0xFFEF4444).withOpacity(0.1),
                          border: Border.all(color: const Color(0xFFEF4444).withOpacity(0.3)),
                          borderRadius: BorderRadius.circular(12),
                        ),
                        child: Row(
                          mainAxisAlignment: MainAxisAlignment.center,
                          children: [
                            const Icon(Icons.error_outline, color: Color(0xFFEF4444), size: 24),
                            const SizedBox(width: 12),
                            Flexible(
                              child: Text(
                                state.message ?? 'Erro desconhecido',
                                style: const TextStyle(
                                  color: Color(0xFFEF4444),
                                  fontWeight: FontWeight.w500,
                                  fontSize: 14,
                                ),
                                textAlign: TextAlign.center,
                              ),
                            ),
                          ],
                        ),
                      ),
                    ],

                    // Action Buttons
                    const SizedBox(height: 24),
                    _buildActionButtons(state, controller),
                  ],
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }

  Widget _buildStatusIcon(PairingStatus status) {
    IconData icon;
    Color color;

    switch (status) {
      case PairingStatus.scanning:
        icon = Icons.qr_code_scanner;
        color = const Color(0xFF6366F1);
        break;
      case PairingStatus.connecting:
        icon = Icons.bluetooth_connected;
        color = const Color(0xFF6366F1);
        break;
      case PairingStatus.pendingApproval:
        icon = Icons.hourglass_empty;
        color = const Color(0xFFF59E0B);
        break;
      case PairingStatus.paired:
        icon = Icons.check_circle;
        color = const Color(0xFF22C55E);
        break;
      case PairingStatus.error:
        icon = Icons.error_outline;
        color = const Color(0xFFEF4444);
        break;
      default:
        icon = Icons.phone_android;
        color = const Color(0xFF5E6A7E);
    }

    return Container(
      width: 64,
      height: 64,
      decoration: BoxDecoration(
        color: color.withOpacity(0.15),
        borderRadius: BorderRadius.circular(20),
      ),
      child: Icon(icon, size: 32, color: color),
    );
  }

  String _getStatusTitle(PairingStatus status) {
    switch (status) {
      case PairingStatus.initial:
        return 'Conectar ao SIRIUS';
      case PairingStatus.scanning:
        return 'Escaneie o QR Code';
      case PairingStatus.connecting:
        return 'Conectando...';
      case PairingStatus.pendingApproval:
        return 'Aguardando Aprovação';
      case PairingStatus.paired:
        return 'Pareado com Sucesso!';
      case PairingStatus.error:
        return 'Erro no Pareamento';
    }
  }

  String _getStatusMessage(PairingStatus status) {
    switch (status) {
      case PairingStatus.initial:
        return 'Toque em "Escanear QR Code" e aponte a câmera para o código exibido no SIRIUS no seu PC';
      case PairingStatus.scanning:
        return 'O QR code aparece quando você clica em "Remote Control" no app SIRIUS';
      case PairingStatus.connecting:
        return 'Estabelecendo conexão segura com o PC...';
      case PairingStatus.pendingApproval:
        return 'O PC precisa confirmar este dispositivo. Verifique a notificação no SIRIUS.';
      case PairingStatus.paired:
        return 'Seu celular está conectado ao SIRIUS. Agora você pode enviar comandos e receber notificações.';
      case PairingStatus.error:
        return 'Tente novamente ou verifique se o PC está na mesma rede';
    }
  }

  Widget _buildActionButtons(PairingState state, PairingController controller) {
    if (state.status == PairingStatus.paired) {
      return const SizedBox.shrink(); // Auto-navigate
    }

    if (state.status == PairingStatus.scanning) {
      return Row(
        children: [
          Expanded(
            child: OutlinedButton.icon(
              onPressed: () {
                setState(() => _showScanner = false);
                _scannerController?.stop();
                controller.pairManually('Sirius Phone');
              },
              icon: const Icon(Icons.keyboard, size: 18),
              label: const Text('Digitar Código'),
              style: OutlinedButton.styleFrom(
                padding: const EdgeInsets.symmetric(vertical: 14),
                side: BorderSide(color: const Color(0xFFFFFFFF).withOpacity(0.2)),
                foregroundColor: Colors.white,
                shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
              ),
            ),
          ),
        ],
      );
    }

    if (state.status == PairingStatus.error) {
      return Row(
        children: [
          Expanded(
            child: OutlinedButton.icon(
              onPressed: () {
                setState(() => _showScanner = true);
                _scannerController?.start();
                controller.startQrScan();
              },
              icon: const Icon(Icons.qr_code_scanner, size: 18),
              label: const Text('Tentar QR Code'),
              style: OutlinedButton.styleFrom(
                padding: const EdgeInsets.symmetric(vertical: 14),
                side: BorderSide(color: const Color(0xFFFFFFFF).withOpacity(0.2)),
                foregroundColor: Colors.white,
                shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
              ),
            ),
          ),
          const SizedBox(width: 12),
          Expanded(
            child: ElevatedButton.icon(
              onPressed: () => controller.pairManually('Sirius Phone'),
              icon: const Icon(Icons.keyboard, size: 18),
              label: const Text('Digitar Código'),
              style: ElevatedButton.styleFrom(
                padding: const EdgeInsets.symmetric(vertical: 14),
                backgroundColor: const Color(0xFF6366F1),
                foregroundColor: Colors.white,
                shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
              ),
            ),
          ),
        ],
      );
    }

    // Initial state
    return Column(
      children: [
        ElevatedButton.icon(
          onPressed: () {
            setState(() => _showScanner = true);
            _scannerController?.start();
            controller.startQrScan();
          },
          icon: const Icon(Icons.qr_code_scanner, size: 20),
          label: const Text('ESCANEAR QR CODE'),
          style: ElevatedButton.styleFrom(
            minimumSize: const Size(double.infinity, 52),
            backgroundColor: const Color(0xFF6366F1),
            foregroundColor: Colors.white,
            shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(14)),
            textStyle: const TextStyle(fontWeight: FontWeight.w700, letterSpacing: 1),
          ),
        ),
        const SizedBox(height: 12),
        OutlinedButton.icon(
          onPressed: () => controller.pairManually('Sirius Phone'),
          icon: const Icon(Icons.keyboard, size: 18),
          label: const Text('DIGITAR CÓDIGO MANUAL'),
          style: OutlinedButton.styleFrom(
            minimumSize: const Size(double.infinity, 52),
            side: BorderSide(color: const Color(0xFFFFFFFF).withOpacity(0.2)),
            foregroundColor: Colors.white,
            shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(14)),
            textStyle: const TextStyle(fontWeight: FontWeight.w600),
          ),
        ),
      ],
    );
  }
}