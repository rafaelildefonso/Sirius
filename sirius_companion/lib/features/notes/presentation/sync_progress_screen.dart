import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../application/note_sync_service.dart';

class SyncProgressScreen extends ConsumerWidget {
  const SyncProgressScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final progress = ref.watch(noteSyncServiceProvider);

    return Scaffold(
      backgroundColor: const Color(0xFF07090F),
      appBar: AppBar(
        title: const Text('Sincronização'),
        backgroundColor: const Color(0xFF07090F),
      ),
      body: Padding(
        padding: const EdgeInsets.all(20),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            _StatusCard(progress: progress),
            const SizedBox(height: 24),
            if (progress.state == NoteSyncState.syncing) ...[
              const Text('Progresso', style: TextStyle(
                color: Color(0xFF9CA3AF),
                fontSize: 13,
                fontWeight: FontWeight.w600,
              )),
              const SizedBox(height: 12),
              LinearProgressIndicator(
                value: progress.totalItems > 0
                    ? progress.currentItem / progress.totalItems
                    : 0,
                backgroundColor: const Color(0xFF1F2937),
                valueColor: const AlwaysStoppedAnimation(Color(0xFF22C55E)),
                minHeight: 8,
                borderRadius: BorderRadius.circular(4),
              ),
              const SizedBox(height: 12),
              _StatRow(label: 'Itens', value: '${progress.currentItem} / ${progress.totalItems}'),
              _StatRow(
                label: 'Enviado',
                value: _formatBytes(progress.bytesSent),
              ),
              _StatRow(
                label: 'Total',
                value: _formatBytes(progress.totalBytes),
              ),
              _StatRow(
                label: 'Velocidade',
                value: '${_formatBytes(progress.speedBps.toInt())}/s',
              ),
              if (progress.totalBytes > 0 && progress.bytesSent > 0) ...[
                const SizedBox(height: 8),
                _StatRow(
                  label: 'ETA',
                  value: _estimateEta(progress),
                ),
              ],
            ],
            const Spacer(),
            if (progress.state == NoteSyncState.completed ||
                progress.state == NoteSyncState.error)
              SizedBox(
                width: double.infinity,
                child: FilledButton(
                  onPressed: () => Navigator.pop(context),
                  style: FilledButton.styleFrom(
                    backgroundColor: const Color(0xFF6366F1),
                    padding: const EdgeInsets.symmetric(vertical: 14),
                    shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(14)),
                  ),
                  child: const Text('Voltar'),
                ),
              ),
          ],
        ),
      ),
    );
  }

  String _formatBytes(int bytes) {
    if (bytes < 1024) return '$bytes B';
    if (bytes < 1024 * 1024) return '${(bytes / 1024).toStringAsFixed(1)} KB';
    return '${(bytes / (1024 * 1024)).toStringAsFixed(1)} MB';
  }

  String _estimateEta(NoteSyncProgress progress) {
    if (progress.speedBps <= 0) return 'Calculando...';
    final remaining = progress.totalBytes - progress.bytesSent;
    final seconds = (remaining / progress.speedBps).round();
    if (seconds < 60) return '${seconds}s';
    final minutes = seconds ~/ 60;
    final secs = seconds % 60;
    return '${minutes}m ${secs}s';
  }
}

class _StatusCard extends StatelessWidget {
  final NoteSyncProgress progress;
  const _StatusCard({required this.progress});

  @override
  Widget build(BuildContext context) {
    IconData icon;
    Color color;
    String title;
    String subtitle;

    switch (progress.state) {
      case NoteSyncState.idle:
        icon = Icons.cloud_upload;
        color = const Color(0xFF9CA3AF);
        title = 'Aguardando';
        subtitle = 'Nenhuma sincronização em andamento';
        break;
      case NoteSyncState.connecting:
        icon = Icons.sync;
        color = const Color(0xFFFBBF24);
        title = 'Conectando';
        subtitle = 'Estabelecendo conexão com o PC...';
        break;
      case NoteSyncState.syncing:
        icon = Icons.cloud_sync;
        color = const Color(0xFF22C55E);
        title = 'Sincronizando';
        subtitle = 'Enviando anotações...';
        break;
      case NoteSyncState.completed:
        icon = Icons.check_circle;
        color = const Color(0xFF22C55E);
        title = 'Concluído';
        subtitle = '${progress.totalItems} anotação(ões) sincronizada(s)';
        break;
      case NoteSyncState.error:
        icon = Icons.error_outline;
        color = const Color(0xFFEF4444);
        title = 'Erro';
        subtitle = progress.error ?? 'Falha na sincronização';
        break;
    }

    return Container(
      padding: const EdgeInsets.all(20),
      decoration: BoxDecoration(
        color: color.withOpacity(0.08),
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: color.withOpacity(0.2)),
      ),
      child: Row(
        children: [
          Container(
            width: 48,
            height: 48,
            decoration: BoxDecoration(
              color: color.withOpacity(0.15),
              borderRadius: BorderRadius.circular(12),
            ),
            child: Icon(icon, color: color, size: 24),
          ),
          const SizedBox(width: 16),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(title, style: TextStyle(
                  color: color,
                  fontSize: 16,
                  fontWeight: FontWeight.w600,
                )),
                const SizedBox(height: 2),
                Text(subtitle, style: const TextStyle(
                  color: Color(0xFF9CA3AF),
                  fontSize: 13,
                )),
              ],
            ),
          ),
          if (progress.state == NoteSyncState.syncing)
            SizedBox(
              width: 20,
              height: 20,
              child: CircularProgressIndicator(
                strokeWidth: 2,
                valueColor: AlwaysStoppedAnimation(color),
              ),
            ),
        ],
      ),
    );
  }
}

class _StatRow extends StatelessWidget {
  final String label;
  final String value;
  const _StatRow({required this.label, required this.value});

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 4),
      child: Row(
        mainAxisAlignment: MainAxisAlignment.spaceBetween,
        children: [
          Text(label, style: const TextStyle(color: Color(0xFF5E6A7E), fontSize: 13)),
          Text(value, style: const TextStyle(color: Colors.white, fontSize: 13, fontWeight: FontWeight.w500)),
        ],
      ),
    );
  }
}
