import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'dart:async';
import 'package:permission_handler/permission_handler.dart';
import '../application/home_controller.dart';
import '../../../../core/storage/models/sync_item.dart' as sync_model;
import '../../../../core/device_identity.dart';
import '../../../../core/storage/database/database.dart';
import '../../../../core/ai/ai_service.dart';
import '../../../../core/ai/gemma_engine.dart';
import '../../../../core/ai/hf_auth_webview.dart';
import '../../../../features/tasks/task_alarm_service.dart';
import '../../locations/presentation/places_screen.dart';

class HomeScreen extends ConsumerStatefulWidget {
  const HomeScreen({super.key});

  @override
  ConsumerState<HomeScreen> createState() => _HomeScreenState();
}

class _HomeScreenState extends ConsumerState<HomeScreen> {
  int _taskTick = 0;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      ref.read(homeControllerProvider.notifier).loadStatus();
    });
  }

  void _refreshTasks() {
    if (mounted) setState(() => _taskTick++);
  }

  void _navigateToPlaces() {
    Navigator.push(
      context,
      MaterialPageRoute(builder: (_) => const PlacesScreen()),
    );
  }

  @override
  Widget build(BuildContext context) {
    final state = ref.watch(homeControllerProvider);
    final controller = ref.read(homeControllerProvider.notifier);

    return Scaffold(
      backgroundColor: const Color(0xFF07090F),
      appBar: AppBar(
        title: const Text('SIRIUS Companion'),
        actions: [
          IconButton(
            icon: const Icon(Icons.settings_outlined),
            onPressed: () => _showSettings(context),
          ),
        ],
      ),
      body: RefreshIndicator(
        onRefresh: () async {
          await ref.read(homeControllerProvider.notifier).loadStatus();
          _refreshTasks();
        },
        color: const Color(0xFF6366F1),
        child: ListView(
          padding: const EdgeInsets.all(16),
          children: [
            _ConnectionStatusCard(state: state),
            const SizedBox(height: 16),
            const _AlarmPermissionBanner(),
            const SizedBox(height: 16),
            _TaskQuickAddCard(onCreated: _refreshTasks),
            const SizedBox(height: 16),
            _UpcomingTasksSection(tick: _taskTick, onChanged: _refreshTasks),
            const SizedBox(height: 16),
            _QuickActions(
              isSyncing: state.isSyncing,
              onSync: () => controller.triggerManualSync(),
              onUnpair: () => _showUnpairDialog(context, ref.read(homeControllerProvider.notifier)),
              onPlaces: _navigateToPlaces,
            ),
            const SizedBox(height: 16),
            _StatsRow(
              pendingCount: state.pendingCount,
              failedCount: state.failedCount,
              lastSync: state.lastSync,
            ),
            const SizedBox(height: 16),
            _RecentCommandsSection(commands: state.recentCommands),
            const SizedBox(height: 16),
            if (state.lastSync != null || state.lastError != null)
              _LastSyncInfo(lastSync: state.lastSync, lastError: state.lastError),
          ],
        ),
      ),
    );
  }

  void _showSettings(BuildContext context) {
    Navigator.push(
      context,
      MaterialPageRoute(builder: (_) => const SettingsScreen()),
    );
  }

  void _showUnpairDialog(BuildContext context, HomeController controller) {
    showDialog(
      context: context,
      builder: (ctx) => AlertDialog(
        backgroundColor: const Color(0xFF0D1117),
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
        title: const Text('Desparear Dispositivo', style: TextStyle(color: Colors.white)),
        content: const Text(
          'Isso removerá o pareamento com o PC. Você precisará escanear o QR code novamente para reconectar.',
          style: TextStyle(color: Color(0xFF9CA3AF)),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx),
            child: const Text('Cancelar', style: TextStyle(color: Color(0xFF9CA3AF))),
          ),
          FilledButton(
            onPressed: () {
              Navigator.pop(ctx);
              controller.unpair();
            },
            style: FilledButton.styleFrom(backgroundColor: const Color(0xFFEF4444)),
            child: const Text('Desparear'),
          ),
        ],
      ),
    );
  }
}

/// Warns when the permissions needed for task alarms to actually ring are
/// missing (notifications, exact alarms). Hidden once everything is granted.
class _AlarmPermissionBanner extends StatefulWidget {
  const _AlarmPermissionBanner();

  @override
  State<_AlarmPermissionBanner> createState() => _AlarmPermissionBannerState();
}

class _AlarmPermissionBannerState extends State<_AlarmPermissionBanner> {
  bool _checking = true;
  bool _missingNotification = false;
  bool _missingExactAlarm = false;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) => _check());
  }

  Future<void> _check({bool request = false}) async {
    try {
      var notif = await Permission.notification.status;
      if (request && !notif.isGranted) {
        notif = await Permission.notification.request();
      }
      var exact = await Permission.scheduleExactAlarm.status;
      if (request && !exact.isGranted) {
        try {
          exact = await Permission.scheduleExactAlarm.request();
        } catch (_) {}
      }
      if (!mounted) return;
      setState(() {
        _checking = false;
        _missingNotification = !notif.isGranted;
        _missingExactAlarm = !exact.isGranted;
      });
    } catch (_) {
      if (mounted) setState(() => _checking = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    if (_checking || (!_missingNotification && !_missingExactAlarm)) {
      return const SizedBox.shrink();
    }
    final missing = [
      if (_missingNotification) 'notificações',
      if (_missingExactAlarm) 'alarmes exatos',
    ].join(' e ');

    return Container(
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: const Color(0xFFF59E0B).withValues(alpha: 0.10),
        borderRadius: BorderRadius.circular(16),
        border: Border.all(
          color: const Color(0xFFF59E0B).withValues(alpha: 0.4),
        ),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              const Icon(Icons.alarm_off_rounded,
                  color: Color(0xFFF59E0B), size: 22),
              const SizedBox(width: 10),
              Expanded(
                child: Text(
                  'Sem $missing os alarmes de tarefa podem não tocar.',
                  style: const TextStyle(
                    color: Colors.white,
                    fontSize: 13.5,
                    fontWeight: FontWeight.w600,
                  ),
                ),
              ),
            ],
          ),
          const SizedBox(height: 10),
          Row(
            children: [
              Expanded(
                child: OutlinedButton.icon(
                  onPressed: () => _check(request: true),
                  icon: const Icon(Icons.verified_user_outlined, size: 18),
                  label: const Text('Permitir'),
                ),
              ),
              const SizedBox(width: 10),
              Expanded(
                child: OutlinedButton.icon(
                  onPressed: openAppSettings,
                  icon: const Icon(Icons.settings_outlined, size: 18),
                  label: const Text('Configurações'),
                ),
              ),
            ],
          ),
        ],
      ),
    );
  }
}

class _ConnectionStatusCard extends StatelessWidget {
  final HomeState state;

  const _ConnectionStatusCard({required this.state});

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(20),
      decoration: BoxDecoration(
        color: const Color(0xFFFFFFFF).withValues(alpha: 0.04),
        border: Border.all(color: const Color(0xFFFFFFFF).withValues(alpha: 0.08)),
        borderRadius: BorderRadius.circular(22),
      ),
      child: Column(
        children: [
          Row(
            children: [
              Container(
                width: 12,
                height: 12,
                decoration: BoxDecoration(
                  color: state.isSyncing ? const Color(0xFFF59E0B) : const Color(0xFF22C55E),
                  shape: BoxShape.circle,
                ),
              ),
              const SizedBox(width: 12),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      state.isSyncing ? 'Sincronizando...' : 'Conectado ao SIRIUS',
                      style: const TextStyle(
                        fontSize: 16,
                        fontWeight: FontWeight.w600,
                        color: Colors.white,
                      ),
                    ),
                    const SizedBox(height: 2),
                    Text(
                      'Dispositivo pareado e pronto para uso',
                      style: const TextStyle(fontSize: 12, color: Color(0xFF5E6A7E)),
                    ),
                  ],
                ),
              ),
              if (state.isSyncing)
                const SizedBox(
                  width: 20,
                  height: 20,
                  child: CircularProgressIndicator(
                    strokeWidth: 2,
                    valueColor: AlwaysStoppedAnimation(Color(0xFF6366F1)),
                  ),
                ),
            ],
          ),
        ],
      ),
    );
  }
}

class _QuickActions extends StatelessWidget {
  final bool isSyncing;
  final VoidCallback onSync;
  final VoidCallback onUnpair;
  final VoidCallback onPlaces;

  const _QuickActions({
    required this.isSyncing,
    required this.onSync,
    required this.onUnpair,
    required this.onPlaces,
  });

  @override
  Widget build(BuildContext context) {
    return Column(
      children: [
        Row(
          children: [
            Expanded(
              child: FilledButton.icon(
                onPressed: isSyncing ? null : onSync,
                icon: isSyncing
                    ? const SizedBox(
                        width: 18,
                        height: 18,
                        child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white),
                      )
                    : const Icon(Icons.sync, size: 20),
                label: Text(isSyncing ? 'Sincronizando...' : 'Sincronizar Agora'),
                style: FilledButton.styleFrom(
                  padding: const EdgeInsets.symmetric(vertical: 16),
                  backgroundColor: const Color(0xFF6366F1),
                  shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(14)),
                ),
              ),
            ),
            const SizedBox(width: 12),
            OutlinedButton.icon(
              onPressed: onUnpair,
              icon: const Icon(Icons.link_off, size: 18),
              label: const Text('Desparear'),
              style: OutlinedButton.styleFrom(
                padding: const EdgeInsets.symmetric(vertical: 16, horizontal: 20),
                side: BorderSide(color: const Color(0xFFEF4444).withValues(alpha: 0.5)),
                foregroundColor: const Color(0xFFEF4444),
                shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(14)),
              ),
            ),
          ],
        ),
        const SizedBox(height: 12),
        SizedBox(
          width: double.infinity,
          child: OutlinedButton.icon(
            onPressed: onPlaces,
            icon: const Icon(Icons.place, size: 18),
            label: const Text('Meus Lugares'),
            style: OutlinedButton.styleFrom(
              padding: const EdgeInsets.symmetric(vertical: 16),
              side: BorderSide(color: const Color(0xFF22C55E).withValues(alpha: 0.5)),
              foregroundColor: const Color(0xFF22C55E),
              shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(14)),
            ),
          ),
        ),
      ],
    );
  }
}

class _StatsRow extends StatelessWidget {
  final int pendingCount;
  final int failedCount;
  final DateTime? lastSync;

  const _StatsRow({
    required this.pendingCount,
    required this.failedCount,
    this.lastSync,
  });

  @override
  Widget build(BuildContext context) {
    return Row(
      children: [
        Expanded(
          child: _StatCard(
            icon: Icons.pending_actions,
            label: 'Pendentes',
            value: pendingCount.toString(),
            color: const Color(0xFFF59E0B),
          ),
        ),
        const SizedBox(width: 12),
        Expanded(
          child: _StatCard(
            icon: Icons.error_outline,
            label: 'Falhas',
            value: failedCount.toString(),
            color: const Color(0xFFEF4444),
          ),
        ),
        const SizedBox(width: 12),
        Expanded(
          child: _StatCard(
            icon: Icons.access_time,
            label: 'Último Sync',
            value: lastSync != null
                ? '${lastSync!.hour.toString().padLeft(2, '0')}:${lastSync!.minute.toString().padLeft(2, '0')}'
                : '--:--',
            color: const Color(0xFF6366F1),
          ),
        ),
      ],
    );
  }
}

class _StatCard extends StatelessWidget {
  final IconData icon;
  final String label;
  final String value;
  final Color color;

  const _StatCard({
    required this.icon,
    required this.label,
    required this.value,
    required this.color,
  });

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: const Color(0xFFFFFFFF).withValues(alpha: 0.04),
        border: Border.all(color: const Color(0xFFFFFFFF).withValues(alpha: 0.08)),
        borderRadius: BorderRadius.circular(16),
      ),
      child: Column(
        children: [
          Icon(icon, color: color, size: 24),
          const SizedBox(height: 8),
          Text(
            value,
            style: TextStyle(
              fontSize: 22,
              fontWeight: FontWeight.w700,
              color: color,
            ),
          ),
          const SizedBox(height: 2),
          Text(
            label,
            style: const TextStyle(fontSize: 11, color: Color(0xFF5E6A7E)),
          ),
        ],
      ),
    );
  }
}

class _RecentCommandsSection extends StatelessWidget {
  final List<sync_model.SyncItem> commands;

  const _RecentCommandsSection({required this.commands});

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const Text(
          'Comandos Recentes',
          style: TextStyle(fontSize: 16, fontWeight: FontWeight.w600, color: Colors.white),
        ),
        const SizedBox(height: 12),
        if (commands.isEmpty)
          Container(
            padding: const EdgeInsets.all(24),
            decoration: BoxDecoration(
              color: const Color(0xFFFFFFFF).withValues(alpha: 0.04),
              border: Border.all(color: const Color(0xFFFFFFFF).withValues(alpha: 0.08)),
              borderRadius: BorderRadius.circular(16),
            ),
            child: const Center(
              child: Column(
                children: [
                  Icon(Icons.history, size: 32, color: Color(0xFF5E6A7E)),
                  SizedBox(height: 8),
                  Text(
                    'Nenhum comando recente',
                    style: TextStyle(color: Color(0xFF5E6A7E), fontSize: 14),
                  ),
                  SizedBox(height: 4),
                  Text(
                    'Envie comandos do celular ou do PC',
                    style: TextStyle(color: Color(0xFF5E6A7E), fontSize: 12),
                  ),
                ],
              ),
            ),
          )
        else
          ListView.separated(
            shrinkWrap: true,
            physics: const NeverScrollableScrollPhysics(),
            itemCount: commands.length.clamp(0, 10),
            separatorBuilder: (_, __) => const SizedBox(height: 8),
            itemBuilder: (context, index) {
              final cmd = commands[index];
              return _CommandTile(command: cmd);
            },
          ),
      ],
    );
  }
}

class _CommandTile extends StatelessWidget {
  final sync_model.SyncItem command;

  const _CommandTile({required this.command});

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: const Color(0xFFFFFFFF).withValues(alpha: 0.04),
        border: Border.all(color: const Color(0xFFFFFFFF).withValues(alpha: 0.08)),
        borderRadius: BorderRadius.circular(14),
      ),
      child: Row(
        children: [
          Container(
            width: 8,
            height: 8,
            decoration: BoxDecoration(
              color: command.syncedAt != null
                  ? const Color(0xFF22C55E)
                  : const Color(0xFFF59E0B),
              shape: BoxShape.circle,
            ),
          ),
          const SizedBox(width: 12),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  command.payload['text'] as String? ?? 'Comando',
                  style: const TextStyle(
                    fontSize: 14,
                    fontWeight: FontWeight.w500,
                    color: Colors.white,
                  ),
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                ),
                const SizedBox(height: 2),
                Text(
                  _formatTime(command.createdAt),
                  style: const TextStyle(fontSize: 11, color: Color(0xFF5E6A7E)),
                ),
              ],
            ),
          ),
          if (command.syncedAt != null)
            const Icon(Icons.check_circle, color: Color(0xFF22C55E), size: 20)
          else
            const Icon(Icons.hourglass_empty, color: Color(0xFFF59E0B), size: 20),
        ],
      ),
    );
  }

  String _formatTime(DateTime dt) {
    final now = DateTime.now();
    final diff = now.difference(dt);
    if (diff.inMinutes < 1) return 'agora';
    if (diff.inMinutes < 60) return '${diff.inMinutes}min atrás';
    if (diff.inHours < 24) return '${diff.inHours}h atrás';
    return '${diff.inDays}d atrás';
  }
}

class _LastSyncInfo extends StatelessWidget {
  final DateTime? lastSync;
  final String? lastError;

  const _LastSyncInfo({this.lastSync, this.lastError});

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: const Color(0xFFFFFFFF).withValues(alpha: 0.04),
        border: Border.all(color: const Color(0xFFFFFFFF).withValues(alpha: 0.08)),
        borderRadius: BorderRadius.circular(16),
      ),
child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          Row(
            children: [
              const Icon(Icons.info_outline, size: 18, color: Color(0xFF6366F1)),
              const SizedBox(width: 8),
              const Text(
                'Última Sincronização',
                style: TextStyle(fontSize: 14, fontWeight: FontWeight.w600, color: Colors.white),
              ),
            ],
          ),
          const SizedBox(height: 8),
          Text(
            lastSync != null
                ? '${lastSync!.day}/${lastSync!.month}/${lastSync!.year} ${lastSync!.hour.toString().padLeft(2, '0')}:${lastSync!.minute.toString().padLeft(2, '0')}'
                : 'Nunca sincronizado',
            style: const TextStyle(fontSize: 13, color: Color(0xFF9CA3AF)),
          ),
          lastError != null
              ? Padding(
                  padding: const EdgeInsets.only(top: 8),
                  child: Container(
                    padding: const EdgeInsets.all(10),
                    decoration: BoxDecoration(
                      color: const Color(0xFFEF4444).withValues(alpha: 0.1),
                      borderRadius: BorderRadius.circular(8),
                    ),
                    child: Row(
                      children: [
                        const Icon(Icons.error_outline, size: 16, color: Color(0xFFEF4444)),
                        const SizedBox(width: 8),
                        Expanded(
                          child: Text(
                            lastError!,
                            style: const TextStyle(fontSize: 12, color: Color(0xFFEF4444)),
                          ),
                        ),
                      ],
                    ),
                  ),
                )
              : const SizedBox.shrink(),
        ],
      ),
    );
}
}
class SettingsScreen extends ConsumerStatefulWidget {
  const SettingsScreen({super.key});

  @override
  ConsumerState<SettingsScreen> createState() => _SettingsScreenState();
}

class _SettingsScreenState extends ConsumerState<SettingsScreen> {
  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: const Color(0xFF07090F),
      appBar: AppBar(
        title: const Text('Configurações'),
        backgroundColor: const Color(0xFF07090F),
      ),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          _SectionTitle('Dispositivo'),
          _SettingsTile(
            icon: Icons.phone_android,
            title: 'Device ID',
            subtitle: 'Gerado na primeira instalação',
            trailingIcon: Icons.chevron_right,
            onTap: () => _showDeviceInfo(context),
          ),
          _SettingsTile(
            icon: Icons.info_outline,
            title: 'Versão do App',
            subtitle: '1.0.0',
          ),
          const SizedBox(height: 24),
          _SectionTitle('Pareamento'),
          _SettingsTile(
            icon: Icons.link_off,
            title: 'Desparear do PC',
            subtitle: 'Remove o pareamento atual',
            iconColor: const Color(0xFFEF4444),
            textColor: const Color(0xFFEF4444),
            onTap: () => _showUnpairConfirmation(context),
          ),
          const SizedBox(height: 24),
          _SectionTitle('IA Local (Gemma)'),
          _GemmaStatusTile(),
          const SizedBox(height: 24),
          _SectionTitle('Debug'),
          _SettingsTile(
            icon: Icons.bug_report,
            title: 'Logs de Debug',
            subtitle: 'Ver logs de sincronização',
            onTap: () => _showDebugLogs(context),
          ),
          _SettingsTile(
            icon: Icons.storage,
            title: 'Limpar Dados Locais',
            subtitle: 'Remove banco de dados local (não afeta o PC)',
            iconColor: const Color(0xFFF59E0B),
            textColor: const Color(0xFFF59E0B),
            onTap: () => _showClearDataConfirmation(context),
          ),
        ],
      ),
    );
  }

  void _showDeviceInfo(BuildContext context) {
    showDialog(
      context: context,
      builder: (ctx) => AlertDialog(
        backgroundColor: const Color(0xFF0D1117),
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
        title: const Text('Informações do Dispositivo', style: TextStyle(color: Colors.white)),
        content: FutureBuilder<Map<String, dynamic>>(
          future: _getDeviceInfo(),
          builder: (ctx, snapshot) {
            if (!snapshot.hasData) {
              return const Center(child: CircularProgressIndicator(color: Color(0xFF6366F1)));
            }
            final info = snapshot.data!;
            return Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.start,
              children: info.entries.map((e) => _InfoRow(label: e.key, value: e.value)).toList(),
            );
          }
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context),
            child: const Text('Fechar', style: TextStyle(color: Color(0xFF6366F1))),
          ),
        ],
      ),
    );
  }

  Future<Map<String, String>> _getDeviceInfo() async {
    final deviceId = await DeviceIdentity.getOrCreateId();
    final deviceName = await DeviceIdentity.getDeviceName();
    final paired = await DeviceIdentity.isPaired();
    final pairedAt = await DeviceIdentity.getPairedAt();
    return {
      'Device ID': deviceId,
      'Nome': deviceName,
      'Pareado': paired ? 'Sim' : 'Não',
      'Pareado em': pairedAt?.toString() ?? 'N/A',
    };
  }

  void _showUnpairConfirmation(BuildContext context) {
    showDialog(
      context: context,
      builder: (ctx) => AlertDialog(
        backgroundColor: const Color(0xFF0D1117),
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
        title: const Text('Desparear Dispositivo', style: TextStyle(color: Colors.white)),
        content: const Text(
          'Isso removerá o pareamento com o PC. Você precisará escanear o QR code novamente para reconectar.',
          style: TextStyle(color: Color(0xFF9CA3AF)),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx),
            child: const Text('Cancelar', style: TextStyle(color: Color(0xFF9CA3AF))),
          ),
          FilledButton(
            onPressed: () {
              Navigator.pop(ctx);
              DeviceIdentity.clearPairing();
              ScaffoldMessenger.of(context).showSnackBar(
                const SnackBar(content: Text('Dispositivo despareado')),
              );
            },
            style: FilledButton.styleFrom(backgroundColor: const Color(0xFFEF4444)),
            child: const Text('Desparear'),
          ),
        ],
      ),
    );
  }

  void _showDebugLogs(BuildContext context) {
    Navigator.push(
      context,
      MaterialPageRoute(builder: (_) => const DebugLogsScreen()),
    );
  }

  void _showClearDataConfirmation(BuildContext context) {
    showDialog(
      context: context,
      builder: (ctx) => AlertDialog(
        backgroundColor: const Color(0xFF0D1117),
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
        title: const Text('Limpar Dados Locais', style: TextStyle(color: Colors.white)),
        content: const Text(
          'Isso removerá todo o banco de dados local (comandos, lugares, logs). O pareamento será mantido.',
          style: TextStyle(color: Color(0xFF9CA3AF)),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx),
            child: const Text('Cancelar', style: TextStyle(color: Color(0xFF9CA3AF))),
          ),
          FilledButton(
            onPressed: () async {
              Navigator.pop(ctx);
              final db = AppDatabase();
              await db.deleteAll();
              ScaffoldMessenger.of(context).showSnackBar(
                const SnackBar(content: Text('Dados locais limpos')),
              );
            },
            style: FilledButton.styleFrom(backgroundColor: const Color(0xFFF59E0B)),
            child: const Text('Limpar'),
          ),
        ],
      ),
    );
  }
}

class DebugLogsScreen extends StatelessWidget {
  const DebugLogsScreen({super.key});

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: const Color(0xFF07090F),
      appBar: AppBar(
        title: const Text('Logs de Debug'),
        backgroundColor: const Color(0xFF07090F),
      ),
      body: const Center(
        child: Text('Logs de debug - implementar', style: TextStyle(color: Color(0xFF5E6A7E))),
      ),
    );
  }
}

class _InfoRow extends StatelessWidget {
  final String label;
  final String value;

  const _InfoRow({required this.label, required this.value});

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 6),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          SizedBox(
            width: 100,
            child: Text(label, style: const TextStyle(color: Color(0xFF5E6A7E), fontSize: 13)),
          ),
          Expanded(
            child: Text(value, style: const TextStyle(color: Colors.white, fontSize: 13)),
          ),
        ],
      ),
    );
  }
}

class _GemmaStatusTile extends ConsumerStatefulWidget {
  @override
  _GemmaStatusTileState createState() => _GemmaStatusTileState();
}

class _GemmaStatusTileState extends ConsumerState<_GemmaStatusTile> {
  final _aiService = AiService();
  double _downloadProgress = 0;
  bool _isBusy = false;
  String? _lastError;

  Future<void> _checkAndInitialize() async {
    setState(() {
      _isBusy = true;
      _lastError = null;
    });

    final statusNotifier = ref.read(gemmaStatusProvider.notifier);

    final modelExists = await GemmaEngine.checkModelExists();
    if (!modelExists) {
      await _startAuthFlow();
      setState(() => _isBusy = false);
      return;
    }

    statusNotifier.set(GemmaStatus.downloading);
    setState(() => _downloadProgress = 1);

    final success = await _aiService.initialize();
    statusNotifier.set(success ? GemmaStatus.ready : GemmaStatus.error);
    setState(() => _isBusy = false);
  }

  Future<void> _startAuthFlow() async {
    final result = await Navigator.push<Map<String, String>>(
      context,
      MaterialPageRoute(
        builder: (_) => const HfAuthWebView(),
      ),
    );

    final cookies = result?['cookies'] ?? '';
    final token = result?['token'] ?? '';

    if (cookies.isEmpty && token.isEmpty) {
      if (mounted) {
        ref.read(gemmaStatusProvider.notifier).set(GemmaStatus.error);
        setState(() {
          _isBusy = false;
          _lastError = 'Autenticação cancelada ou falhou. Toque em "Baixar / Inicializar" para tentar novamente.';
        });
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(
            content: Text('Login cancelado. Tente novamente.'),
            backgroundColor: Color(0xFFF59E0B),
            duration: Duration(seconds: 4),
          ),
        );
      }
      return;
    }

    final statusNotifier = ref.read(gemmaStatusProvider.notifier);
    statusNotifier.set(GemmaStatus.downloading);
    setState(() => _downloadProgress = 0);

    try {
      final success = await GemmaEngine.downloadWithCookies(
        cookies,
        token: token,
        onProgress: (p) {
          if (mounted) setState(() => _downloadProgress = p);
        },
      );

      if (success) {
        final initSuccess = await _aiService.initialize();
        statusNotifier.set(initSuccess ? GemmaStatus.ready : GemmaStatus.error);
        if (!initSuccess && mounted) {
          ScaffoldMessenger.of(context).showSnackBar(
            const SnackBar(
              content: Text('Modelo baixado mas falha ao inicializar. Tente reiniciar o app.'),
              backgroundColor: Color(0xFFEF4444),
              duration: Duration(seconds: 5),
            ),
          );
        }
      } else {
        statusNotifier.set(GemmaStatus.error);
        if (mounted) {
          ScaffoldMessenger.of(context).showSnackBar(
            const SnackBar(
              content: Text('Falha ao baixar modelo. Verifique conexão e tente novamente.'),
              backgroundColor: Color(0xFFEF4444),
              duration: Duration(seconds: 5),
            ),
          );
        }
      }
    } catch (e) {
      statusNotifier.set(GemmaStatus.error);
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text('Erro no download: $e'),
            backgroundColor: const Color(0xFFEF4444),
            duration: const Duration(seconds: 5),
          ),
        );
      }
    }
    setState(() => _isBusy = false);
  }

  Future<void> _shutdown() async {
    setState(() => _isBusy = true);
    await _aiService.shutdown();
    ref.read(gemmaStatusProvider.notifier).set(GemmaStatus.unchecked);
    setState(() => _isBusy = false);
  }

  @override
  Widget build(BuildContext context) {
    final status = ref.watch(gemmaStatusProvider);
    final statusNotifier = ref.read(gemmaStatusProvider.notifier);

    return Card(
      color: const Color(0xFFFFFFFF).withValues(alpha: 0.03),
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                const Icon(Icons.psychology, color: Color(0xFF6366F1), size: 24),
                const SizedBox(width: 12),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      const Text(
                        'Modelo: Gemma 3 1B',
                        style: TextStyle(color: Colors.white, fontSize: 14, fontWeight: FontWeight.w500),
                      ),
                      const SizedBox(height: 2),
                      Text(
                        statusNotifier.label,
                        style: TextStyle(
                          color: status == GemmaStatus.ready
                              ? const Color(0xFF22C55E)
                              : status == GemmaStatus.error || status == GemmaStatus.unavailable
                                  ? const Color(0xFFEF4444)
                                  : const Color(0xFFF59E0B),
                          fontSize: 12,
                        ),
                      ),
                    ],
                  ),
                ),
                if (status == GemmaStatus.downloading)
                  SizedBox(
                    width: 24,
                    height: 24,
                    child: CircularProgressIndicator(
                      value: _downloadProgress,
                      strokeWidth: 2,
                      color: const Color(0xFF6366F1),
                    ),
                  )
                else if (status == GemmaStatus.ready)
                  const Icon(Icons.check_circle, color: Color(0xFF22C55E), size: 22)
                else if (status == GemmaStatus.error || status == GemmaStatus.unavailable)
                  const Icon(Icons.error_outline, color: Color(0xFFEF4444), size: 22),
              ],
            ),
            if (status == GemmaStatus.downloading) ...[
              const SizedBox(height: 8),
              ClipRRect(
                borderRadius: BorderRadius.circular(4),
                child: LinearProgressIndicator(
                  value: _downloadProgress,
                  backgroundColor: const Color(0xFF1E293B),
                  valueColor: const AlwaysStoppedAnimation(Color(0xFF6366F1)),
                  minHeight: 4,
                ),
              ),
              const SizedBox(height: 4),
              Text(
                '${(_downloadProgress * 100).toStringAsFixed(0)}% (658 MB)',
                style: const TextStyle(color: Color(0xFF5E6A7E), fontSize: 11),
              ),
            ],
            const SizedBox(height: 8),
            if (status == GemmaStatus.error && _lastError != null) ...[
              Container(
                padding: const EdgeInsets.all(10),
                decoration: BoxDecoration(
                  color: const Color(0xFFEF4444).withValues(alpha: 0.15),
                  borderRadius: BorderRadius.circular(8),
                  border: Border.all(color: const Color(0xFFEF4444).withValues(alpha: 0.3)),
                ),
                child: Row(
                  children: [
                    const Icon(Icons.error_outline, color: Color(0xFFEF4444), size: 16),
                    const SizedBox(width: 8),
                    Expanded(
                      child: Text(
                        _lastError!,
                        style: const TextStyle(color: Color(0xFFEF4444), fontSize: 11),
                      ),
                    ),
                    TextButton(
                      onPressed: _isBusy ? null : () => _checkAndInitialize(),
                      style: TextButton.styleFrom(
                        padding: EdgeInsets.zero,
                        minimumSize: const Size(0, 28),
                        tapTargetSize: MaterialTapTargetSize.shrinkWrap,
                      ),
                      child: const Text('Tentar novamente', style: TextStyle(fontSize: 11, color: Color(0xFF6366F1))),
                    ),
                  ],
                ),
              ),
              const SizedBox(height: 8),
            ],
            Row(
              mainAxisAlignment: MainAxisAlignment.end,
              children: [
                if (status == GemmaStatus.ready)
                  TextButton.icon(
                    onPressed: _isBusy ? null : _shutdown,
                    icon: const Icon(Icons.power_settings_new, size: 16),
                    label: const Text('Descarregar', style: TextStyle(fontSize: 12)),
                    style: TextButton.styleFrom(foregroundColor: const Color(0xFFEF4444)),
                  )
                else if (status != GemmaStatus.downloading)
                  TextButton.icon(
                    onPressed: _isBusy ? null : _checkAndInitialize,
                    icon: Icon(
                      Icons.download,
                      size: 16,
                      color: _isBusy ? const Color(0xFF5E6A7E) : const Color(0xFF6366F1),
                    ),
                    label: Text(
                      _isBusy ? 'Verificando...' : 'Baixar / Inicializar',
                      style: TextStyle(
                        fontSize: 12,
                        color: _isBusy ? const Color(0xFF5E6A7E) : const Color(0xFF6366F1),
                      ),
                    ),
                  ),
              ],
            ),
          ],
        ),
      ),
    );
  }
}

class _SectionTitle extends StatelessWidget {
  final String title;

  const _SectionTitle(this.title);

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(left: 4, bottom: 8),
      child: Text(
        title,
        style: const TextStyle(
          color: Color(0xFF5E6A7E),
          fontSize: 12,
          fontWeight: FontWeight.w600,
          letterSpacing: 1.2,
        ),
      ),
    );
  }
}

class _SettingsTile extends StatelessWidget {
  final IconData icon;
  final String title;
  final String subtitle;
  final IconData? trailingIcon;
  final Color? iconColor;
  final Color? textColor;
  final VoidCallback? onTap;

  const _SettingsTile({
    required this.icon,
    required this.title,
    required this.subtitle,
    this.trailingIcon = Icons.chevron_right,
    this.iconColor,
    this.textColor,
    this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    return ListTile(
      leading: Icon(icon, color: iconColor ?? const Color(0xFF6366F1), size: 24),
      title: Text(title, style: TextStyle(color: textColor ?? Colors.white, fontSize: 15, fontWeight: FontWeight.w500)),
      subtitle: Text(subtitle, style: const TextStyle(color: Color(0xFF5E6A7E), fontSize: 12)),
      trailing: Icon(trailingIcon, color: const Color(0xFF5E6A7E), size: 20),
      onTap: onTap,
      contentPadding: const EdgeInsets.symmetric(horizontal: 4),
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
      tileColor: const Color(0xFFFFFFFF).withValues(alpha: 0.03),
    );
  }
}

// ── Quick task capture ────────────────────────────────────────────────────────

class _TaskQuickAddCard extends StatefulWidget {
  final VoidCallback onCreated;

  const _TaskQuickAddCard({required this.onCreated});

  @override
  State<_TaskQuickAddCard> createState() => _TaskQuickAddCardState();
}

class _TaskQuickAddCardState extends State<_TaskQuickAddCard> {
  final TextEditingController _controller = TextEditingController();
  DateTime? _selectedTime;
  DateTime? _selectedDate;
  bool _saving = false;

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  static String _labelFor(DateTime t) {
    final now = DateTime.now();
    final today = DateTime(now.year, now.month, now.day);
    final target = DateTime(t.year, t.month, t.day);
    final diff = target.difference(today).inDays;
    String dayLabel;
    if (diff == 0) {
      dayLabel = 'Hoje';
    } else if (diff == 1) {
      dayLabel = 'Amanhã';
    } else {
      dayLabel = '${t.day.toString().padLeft(2, '0')}/${t.month.toString().padLeft(2, '0')}';
    }
    return '$dayLabel ${t.hour.toString().padLeft(2, '0')}:${t.minute.toString().padLeft(2, '0')}';
  }

  static String _dateLabel(DateTime d) {
    final now = DateTime.now();
    final today = DateTime(now.year, now.month, now.day);
    final target = DateTime(d.year, d.month, d.day);
    final diff = target.difference(today).inDays;
    if (diff == 0) return 'Hoje';
    if (diff == 1) return 'Amanhã';
    return '${d.day.toString().padLeft(2, '0')}/${d.month.toString().padLeft(2, '0')}';
  }

  Future<void> _pickCustomDate() async {
    final now = DateTime.now();
    final date = await showDatePicker(
      context: context,
      initialDate: _selectedDate ?? now,
      firstDate: now,
      lastDate: now.add(const Duration(days: 365)),
    );
    if (date == null) return;
    setState(() {
      _selectedDate = DateTime(date.year, date.month, date.day);
      if (_selectedTime != null) {
        _selectedTime = DateTime(
          date.year, date.month, date.day,
          _selectedTime!.hour, _selectedTime!.minute,
        );
      }
    });
  }

  Future<void> _pickCustomTime() async {
    final base = _selectedDate ?? DateTime.now();
    final time = await showTimePicker(
      context: context,
      initialTime: TimeOfDay.fromDateTime(base.add(const Duration(hours: 1))),
    );
    if (time == null) return;
    var picked = DateTime(base.year, base.month, base.day, time.hour, time.minute);
    if (picked.isBefore(DateTime.now())) {
      picked = picked.add(const Duration(days: 1));
    }
    setState(() => _selectedTime = picked);
  }

  Future<void> _save() async {
    final title = _controller.text.trim();
    final dueAt = _selectedTime;
    if (title.isEmpty || dueAt == null || _saving) return;
    setState(() => _saving = true);
    try {
      await TaskAlarmService.createQuickTask(title, dueAt);
      if (!mounted) return;
      _controller.clear();
      setState(() {
        _selectedTime = null;
        _selectedDate = null;
      });
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text('Tarefa agendada para ${_labelFor(dueAt)}'),
          backgroundColor: const Color(0xFF22C55E),
          behavior: SnackBarBehavior.floating,
        ),
      );
      widget.onCreated();
    } finally {
      if (mounted) setState(() => _saving = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                const Icon(Icons.bolt_rounded, color: Color(0xFFFBBF24), size: 20),
                const SizedBox(width: 8),
                Text(
                  'ANOTAR TAREFA',
                  style: TextStyle(
                    color: const Color(0xFFFFFFFF).withOpacity(0.9),
                    fontSize: 12,
                    fontWeight: FontWeight.w800,
                    letterSpacing: 1.5,
                  ),
                ),
              ],
            ),
            const SizedBox(height: 12),
            TextField(
              controller: _controller,
              textCapitalization: TextCapitalization.sentences,
              maxLength: 200,
              style: const TextStyle(color: Colors.white),
              decoration: InputDecoration(
                counterText: '',
                hintText: 'Ex.: Ligar pro dentista',
                hintStyle: TextStyle(color: const Color(0xFFFFFFFF).withOpacity(0.3)),
                prefixIcon: const Icon(Icons.edit_note_rounded, color: Color(0xFF6366F1)),
              ),
            ),
            const SizedBox(height: 12),
            Wrap(
              spacing: 8,
              runSpacing: 8,
              children: [
                for (final preset in [
                  ('+15 min', const Duration(minutes: 15)),
                  ('+1 hora', const Duration(hours: 1)),
                  ('+3 horas', const Duration(hours: 3)),
                  ('Manhã', null),
                ])
                  ActionChip(
                    label: Text(preset.$1, style: const TextStyle(fontSize: 12)),
                    labelStyle: const TextStyle(color: Colors.white),
                    backgroundColor: const Color(0xFFFFFFFF).withOpacity(0.06),
                    side: BorderSide(color: const Color(0xFF6366F1).withOpacity(0.4)),
                    onPressed: () {
                      final base = _selectedDate ?? DateTime.now();
                      DateTime t;
                      if (preset.$2 != null) {
                        t = base.add(preset.$2!);
                      } else {
                        t = DateTime(base.year, base.month, base.day, 9);
                        if (t.isBefore(DateTime.now())) t = t.add(const Duration(days: 1));
                      }
                      setState(() => _selectedTime = t);
                    },
                  ),
                ActionChip(
                  avatar: Icon(
                    Icons.calendar_today_rounded,
                    size: 16,
                    color: _selectedDate != null ? const Color(0xFF22C55E) : Colors.white70,
                  ),
                  label: Text(
                    _selectedDate == null ? 'Hoje' : _dateLabel(_selectedDate!),
                    style: TextStyle(
                      fontSize: 12,
                      color: _selectedDate != null ? const Color(0xFF22C55E) : Colors.white,
                      fontWeight: _selectedDate != null ? FontWeight.w700 : FontWeight.w400,
                    ),
                  ),
                  backgroundColor: const Color(0xFFFFFFFF).withOpacity(0.06),
                  side: BorderSide(color: const Color(0xFF6366F1).withOpacity(0.4)),
                  onPressed: _pickCustomDate,
                ),
                ActionChip(
                  avatar: Icon(
                    Icons.schedule_rounded,
                    size: 16,
                    color: _selectedTime != null ? const Color(0xFF22C55E) : Colors.white70,
                  ),
                  label: Text(
                    _selectedTime == null ? 'Escolher hora' : _labelFor(_selectedTime!),
                    style: TextStyle(
                      fontSize: 12,
                      color: _selectedTime != null
                          ? const Color(0xFF22C55E)
                          : Colors.white,
                      fontWeight: _selectedTime != null ? FontWeight.w700 : FontWeight.w400,
                    ),
                  ),
                  backgroundColor: const Color(0xFFFFFFFF).withOpacity(0.06),
                  side: BorderSide(color: const Color(0xFF6366F1).withOpacity(0.4)),
                  onPressed: _pickCustomTime,
                ),
              ],
            ),
            const SizedBox(height: 14),
            SizedBox(
              width: double.infinity,
              child: FilledButton.icon(
                onPressed: (_saving || _controller.text.trim().isEmpty || _selectedTime == null)
                    ? null
                    : _save,
                icon: _saving
                    ? const SizedBox(
                        width: 18,
                        height: 18,
                        child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white),
                      )
                    : const Icon(Icons.alarm_add_rounded),
                label: const Text('Agendar alarme'),
                style: FilledButton.styleFrom(
                  padding: const EdgeInsets.symmetric(vertical: 14),
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _UpcomingTasksSection extends StatelessWidget {
  final int tick;
  final VoidCallback onChanged;

  const _UpcomingTasksSection({required this.tick, required this.onChanged});

  String _dueLabel(DateTime t) {
    final diff = t.difference(DateTime.now());
    if (diff.isNegative) return 'agora';
    if (diff.inMinutes < 60) return 'em ${diff.inMinutes} min';
    if (diff.inHours < 24) return 'em ${(diff.inMinutes / 60).round()} h';
    return '${t.day}/${t.month} ${t.hour.toString().padLeft(2, '0')}:${t.minute.toString().padLeft(2, '0')}';
  }

  @override
  Widget build(BuildContext context) {
    return FutureBuilder<List<ScheduledTask>>(
      key: ValueKey(tick),
      future: TaskAlarmService.getPendingTasks(),
      builder: (context, snapshot) {
        final tasks = snapshot.data ?? [];
        if (tasks.isEmpty) {
          return const _SectionTitle('PRÓXIMAS TAREFAS');
        }
        return Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const _SectionTitle('PRÓXIMAS TAREFAS'),
            ...tasks.take(5).map((task) => Card(
                  margin: const EdgeInsets.only(bottom: 8),
                  child: ListTile(
                    leading: Icon(
                      task.dueAt.isBefore(DateTime.now())
                          ? Icons.notifications_active_rounded
                          : Icons.alarm_rounded,
                      color: task.dueAt.isBefore(DateTime.now())
                          ? const Color(0xFFEF4444)
                          : const Color(0xFF6366F1),
                    ),
                    title: Text(
                      task.title,
                      maxLines: 2,
                      overflow: TextOverflow.ellipsis,
                      style: const TextStyle(color: Colors.white, fontSize: 14, fontWeight: FontWeight.w600),
                    ),
                    subtitle: Text(
                      _dueLabel(task.dueAt),
                      style: const TextStyle(color: Color(0xFF9CA3AF), fontSize: 12),
                    ),
                    trailing: IconButton(
                      icon: const Icon(Icons.check_circle_outline_rounded, color: Color(0xFF22C55E)),
                      tooltip: 'Concluir',
                      onPressed: () async {
                        await TaskAlarmService.markDone(task.remoteId);
                        onChanged();
                      },
                    ),
                  ),
                )),
          ],
        );
      },
    );
  }
}