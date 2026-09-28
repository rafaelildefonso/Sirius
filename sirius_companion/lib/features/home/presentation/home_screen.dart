import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'dart:async';
import 'package:permission_handler/permission_handler.dart';
import 'package:shared_preferences/shared_preferences.dart';
import '../application/home_controller.dart';
import '../../../../core/storage/models/sync_item.dart' as sync_model;
import '../../../../core/storage/repositories/note_repository.dart';
import '../../../../core/device_identity.dart';
import '../../../../core/storage/database/database.dart';
import '../../../../core/ai/ai_service.dart';
import '../../../../core/ai/gemma_engine.dart';
import '../../../../core/ai/hf_auth_webview.dart';
import '../../../../features/tasks/task_alarm_service.dart';
import '../../../../features/tasks/presentation/create_task_screen.dart';
import '../../locations/presentation/places_screen.dart';
import '../../notes/presentation/notes_screen.dart';
import '../../notes/presentation/note_editor_screen.dart';
import '../../pairing/presentation/pairing_screen.dart';

class HomeScreen extends ConsumerStatefulWidget {
  const HomeScreen({super.key});

  @override
  ConsumerState<HomeScreen> createState() => _HomeScreenState();
}

class _HomeScreenState extends ConsumerState<HomeScreen>
    with WidgetsBindingObserver {
  int _taskTick = 0;
  AppLifecycleListener? _lifecycleListener;
  Timer? _taskRefreshTimer;

  @override
  void initState() {
    super.initState();
    _lifecycleListener = AppLifecycleListener(
      onResume: () async {
        await ref.read(homeControllerProvider.notifier).loadStatus();
        await ref.read(homeControllerProvider.notifier).checkConnectivity();
        _refreshTasks();
      },
    );
    // SQLite writes made by WorkManager/foreground background services can
    // happen in another isolate, so Drift's stream is not always notified in
    // this UI isolate. Recreate the query periodically while this screen is
    // visible so synced tasks appear without closing and reopening the app.
    _taskRefreshTimer = Timer.periodic(const Duration(seconds: 10), (_) {
      if (mounted) _refreshTasks();
    });
    WidgetsBinding.instance.addPostFrameCallback((_) {
      ref.read(homeControllerProvider.notifier).loadStatus();
      ref.read(homeControllerProvider.notifier).checkConnectivity();
    });
  }

  @override
  void dispose() {
    _taskRefreshTimer?.cancel();
    _lifecycleListener?.dispose();
    super.dispose();
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

  void _navigateToNotes() {
    Navigator.push(
      context,
      MaterialPageRoute(builder: (_) => const NotesScreen()),
    );
  }

  void _openQuickTaskModal() async {
    final result = await Navigator.push<bool>(
      context,
      MaterialPageRoute(builder: (_) => const CreateTaskScreen()),
    );
    if (result == true) {
      _refreshTasks();
    }
  }

  void _openQuickNoteModal() {
    Navigator.push(
      context,
      MaterialPageRoute(builder: (_) => const NoteEditorScreen()),
    );
  }

  @override
  Widget build(BuildContext context) {
    final state = ref.watch(homeControllerProvider);
    final controller = ref.read(homeControllerProvider.notifier);
    final serverUrlFuture = DeviceIdentity.getServerUrl();

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
          await ref.read(homeControllerProvider.notifier).checkConnectivity();
          _refreshTasks();
        },
        color: const Color(0xFF6366F1),
        child: ListView(
          padding: const EdgeInsets.all(16),
          children: [
            FutureBuilder<String?>(
              future: serverUrlFuture,
              builder: (context, snapshot) {
                return _ConnectionStatusCard(
                  state: state,
                  onRefresh: () => controller.checkConnectivity(),
                  serverUrl: snapshot.data,
                );
              },
            ),
            const SizedBox(height: 16),
            const _AlarmPermissionBanner(),
            const SizedBox(height: 16),
            _QuickActionButtons(
              onQuickTask: _openQuickTaskModal,
              onQuickNote: _openQuickNoteModal,
            ),
            const SizedBox(height: 16),
            _UpcomingTasksSection(tick: _taskTick, onChanged: _refreshTasks),
            const SizedBox(height: 16),
            _QuickActions(
              isSyncing: state.isSyncing,
              onSync: () async {
                final result = await controller.triggerManualSync();
                // The sync writes tasks into SQLite after this screen has
                // already built its FutureBuilder. Force the task section to
                // read the freshly pulled rows immediately.
                _refreshTasks();
                if (!mounted) return;
                if (result != null) {
                  if (result.success) {
                    // Show detailed success dialog
                    showDialog(
                      context: context,
                      builder: (ctx) => AlertDialog(
                        backgroundColor: const Color(0xFF0D1117),
                        shape: RoundedRectangleBorder(
                          borderRadius: BorderRadius.circular(16),
                        ),
                        title: const Row(
                          children: [
                            Icon(
                              Icons.check_circle,
                              color: Color(0xFF22C55E),
                              size: 24,
                            ),
                            SizedBox(width: 10),
                            Expanded(
                              child: Text(
                                'Sincronização Concluída',
                                style: TextStyle(
                                  color: Colors.white,
                                  fontSize: 18,
                                  fontWeight: FontWeight.w600,
                                ),
                              ),
                            ),
                          ],
                        ),
                        content: Column(
                          mainAxisSize: MainAxisSize.min,
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            const Text(
                              'Itens enviados ao PC:',
                              style: TextStyle(
                                color: Color(0xFF9CA3AF),
                                fontSize: 12,
                                fontWeight: FontWeight.w600,
                              ),
                            ),
                            const SizedBox(height: 8),
                            if (result.notesSent > 0)
                              _SyncDetailRow(
                                icon: Icons.note_alt_outlined,
                                label: 'Anotações (migradas pro PC)',
                                count: result.notesSent,
                                color: const Color(0xFF6366F1),
                              ),
                            if (result.visitsSent > 0)
                              _SyncDetailRow(
                                icon: Icons.place,
                                label: 'Visitas a locais',
                                count: result.visitsSent,
                                color: const Color(0xFF22C55E),
                              ),
                            if (result.syncItemsSent > 0)
                              _SyncDetailRow(
                                icon: Icons.sync,
                                label: 'Comandos/Tarefas',
                                count: result.syncItemsSent,
                                color: const Color(0xFFF59E0B),
                              ),
                            if (result.notesSent == 0 &&
                                result.visitsSent == 0 &&
                                result.syncItemsSent == 0)
                              const Padding(
                                padding: EdgeInsets.symmetric(vertical: 8),
                                child: Text(
                                  'Nenhum item novo para enviar',
                                  style: TextStyle(color: Color(0xFF5E6A7E)),
                                ),
                              ),
                            const SizedBox(height: 16),
                            const Text(
                              'Itens recebidos do PC:',
                              style: TextStyle(
                                color: Color(0xFF9CA3AF),
                                fontSize: 12,
                                fontWeight: FontWeight.w600,
                              ),
                            ),
                            const SizedBox(height: 8),
                            if (result.itemsPulled > 0)
                              _SyncDetailRow(
                                icon: Icons.download,
                                label: 'Tarefas/Comandos',
                                count: result.itemsPulled,
                                color: const Color(0xFF6366F1),
                              )
                            else
                              const Padding(
                                padding: EdgeInsets.symmetric(vertical: 8),
                                child: Text(
                                  'Nenhuma atualização nova',
                                  style: TextStyle(color: Color(0xFF5E6A7E)),
                                ),
                              ),
                            const SizedBox(height: 16),
                            const Divider(color: Color(0xFF374151)),
                            const SizedBox(height: 8),
                            Text(
                              'Total: ${result.notesSent + result.visitsSent + result.syncItemsSent} enviados, ${result.itemsPulled} recebidos',
                              style: const TextStyle(
                                color: Colors.white,
                                fontWeight: FontWeight.w600,
                              ),
                            ),
                            const SizedBox(height: 4),
                            const Text(
                              '✓ Anotações salvas no PC • Tarefas mantidas no celular',
                              style: TextStyle(
                                color: Color(0xFF22C55E),
                                fontSize: 11,
                              ),
                            ),
                          ],
                        ),
                        actions: [
                          TextButton(
                            onPressed: () => Navigator.pop(ctx),
                            child: const Text(
                              'OK',
                              style: TextStyle(color: Color(0xFF6366F1)),
                            ),
                          ),
                        ],
                      ),
                    );
                  } else {
                    // Show error dialog
                    showDialog(
                      context: context,
                      builder: (ctx) => AlertDialog(
                        backgroundColor: const Color(0xFF0D1117),
                        shape: RoundedRectangleBorder(
                          borderRadius: BorderRadius.circular(16),
                        ),
                        title: const Row(
                          children: [
                            Icon(
                              Icons.error_outline,
                              color: Color(0xFFEF4444),
                              size: 24,
                            ),
                            SizedBox(width: 10),
                            Expanded(
                              child: Text(
                                'Falha na Sincronização',
                                style: TextStyle(
                                  color: Colors.white,
                                  fontSize: 18,
                                  fontWeight: FontWeight.w600,
                                ),
                              ),
                            ),
                          ],
                        ),
                        content: Text(
                          result.error ?? 'Erro desconhecido',
                          style: const TextStyle(color: Color(0xFF9CA3AF)),
                        ),
                        actions: [
                          TextButton(
                            onPressed: () => Navigator.pop(ctx),
                            child: const Text(
                              'OK',
                              style: TextStyle(color: Color(0xFFEF4444)),
                            ),
                          ),
                        ],
                      ),
                    );
                  }
                }
              },
              onUnpair: () => _showUnpairDialog(context, controller),
              onPlaces: _navigateToPlaces,
              onNotes: _navigateToNotes,
            ),
            const SizedBox(height: 16),
            _StatsRow(
              pendingCount: state.pendingCount,
              failedCount: state.failedCount,
              pendingNotesCount: state.pendingNotesCount,
              pendingVisitsCount: state.pendingVisitsCount,
              totalPendingCount: state.totalPendingCount,
              lastSync: state.lastSync,
            ),
            const SizedBox(height: 16),
            _RecentCommandsSection(commands: state.recentCommands),
            const SizedBox(height: 16),
            if (state.lastSync != null || state.lastError != null)
              _LastSyncInfo(
                lastSync: state.lastSync,
                lastError: state.lastError,
              ),
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
        title: const Text(
          'Desparear Dispositivo',
          style: TextStyle(color: Colors.white),
        ),
        content: const Text(
          'Isso removerá o pareamento com o PC. Você precisará escanear o QR code novamente para reconectar.',
          style: TextStyle(color: Color(0xFF9CA3AF)),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx),
            child: const Text(
              'Cancelar',
              style: TextStyle(color: Color(0xFF9CA3AF)),
            ),
          ),
          FilledButton(
            onPressed: () async {
              Navigator.pop(ctx);
              await controller.unpair();
              if (!mounted) return;
              // Update the reactive paired provider
              ref.read(isPairedProvider.notifier).state = false;
              // Navigate to pairing screen, clearing the stack
              Navigator.of(context).pushAndRemoveUntil(
                MaterialPageRoute(builder: (_) => const _PairingRedirect()),
                (route) => false,
              );
            },
            style: FilledButton.styleFrom(
              backgroundColor: const Color(0xFFEF4444),
            ),
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
              const Icon(
                Icons.alarm_off_rounded,
                color: Color(0xFFF59E0B),
                size: 22,
              ),
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
  final VoidCallback onRefresh;
  final String? serverUrl;

  const _ConnectionStatusCard({
    required this.state,
    required this.onRefresh,
    this.serverUrl,
  });

  @override
  Widget build(BuildContext context) {
    final connected = state.isConnected;
    final syncing = state.isSyncing;
    String displayUrl = 'IP desconhecido';
    final url = serverUrl;
    if (url != null) {
      try {
        final uri = Uri.parse(url);
        displayUrl = '${uri.host}:${uri.port}';
      } catch (_) {
        displayUrl = url;
      }
    }

    return Container(
      padding: const EdgeInsets.all(20),
      decoration: BoxDecoration(
        color: const Color(0xFFFFFFFF).withValues(alpha: 0.04),
        border: Border.all(
          color: connected
              ? const Color(0xFF22C55E).withValues(alpha: 0.3)
              : const Color(0xFFEF4444).withValues(alpha: 0.3),
        ),
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
                  color: syncing
                      ? const Color(0xFFF59E0B)
                      : connected
                      ? const Color(0xFF22C55E)
                      : const Color(0xFFEF4444),
                  shape: BoxShape.circle,
                ),
              ),
              const SizedBox(width: 12),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      syncing
                          ? 'Sincronizando...'
                          : connected
                          ? 'Conectado ao SIRIUS'
                          : 'Desconectado do SIRIUS',
                      style: TextStyle(
                        fontSize: 16,
                        fontWeight: FontWeight.w600,
                        color: connected
                            ? Colors.white
                            : const Color(0xFFEF4444),
                      ),
                    ),
                    const SizedBox(height: 2),
                    Text(
                      syncing
                          ? (state.syncProgressMessage ?? 'Processando...')
                          : connected
                          ? 'Conectado em $displayUrl'
                          : 'PC não encontrado na rede local',
                      style: const TextStyle(
                        fontSize: 12,
                        color: Color(0xFF5E6A7E),
                      ),
                    ),
                  ],
                ),
              ),
              if (syncing)
                const SizedBox(
                  width: 20,
                  height: 20,
                  child: CircularProgressIndicator(
                    strokeWidth: 2,
                    valueColor: AlwaysStoppedAnimation(Color(0xFF6366F1)),
                  ),
                )
              else if (!connected)
                IconButton(
                  icon: const Icon(
                    Icons.refresh,
                    color: Color(0xFFEF4444),
                    size: 20,
                  ),
                  onPressed: onRefresh,
                  tooltip: 'Verificar Conexão',
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
  final VoidCallback onNotes;

  const _QuickActions({
    required this.isSyncing,
    required this.onSync,
    required this.onUnpair,
    required this.onPlaces,
    required this.onNotes,
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
                        child: CircularProgressIndicator(
                          strokeWidth: 2,
                          color: Colors.white,
                        ),
                      )
                    : const Icon(Icons.sync, size: 20),
                label: Text(
                  isSyncing ? 'Sincronizando...' : 'Sincronizar Agora',
                ),
                style: FilledButton.styleFrom(
                  padding: const EdgeInsets.symmetric(vertical: 16),
                  backgroundColor: const Color(0xFF6366F1),
                  shape: RoundedRectangleBorder(
                    borderRadius: BorderRadius.circular(14),
                  ),
                ),
              ),
            ),
            const SizedBox(width: 12),
            OutlinedButton.icon(
              onPressed: onUnpair,
              icon: const Icon(Icons.link_off, size: 18),
              label: const Text('Desparear'),
              style: OutlinedButton.styleFrom(
                padding: const EdgeInsets.symmetric(
                  vertical: 16,
                  horizontal: 20,
                ),
                side: BorderSide(
                  color: const Color(0xFFEF4444).withValues(alpha: 0.5),
                ),
                foregroundColor: const Color(0xFFEF4444),
                shape: RoundedRectangleBorder(
                  borderRadius: BorderRadius.circular(14),
                ),
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
              side: BorderSide(
                color: const Color(0xFF22C55E).withValues(alpha: 0.5),
              ),
              foregroundColor: const Color(0xFF22C55E),
              shape: RoundedRectangleBorder(
                borderRadius: BorderRadius.circular(14),
              ),
            ),
          ),
        ),
        const SizedBox(height: 12),
        SizedBox(
          width: double.infinity,
          child: OutlinedButton.icon(
            onPressed: onNotes,
            icon: const Icon(Icons.note_alt_outlined, size: 18),
            label: const Text('Anotações'),
            style: OutlinedButton.styleFrom(
              padding: const EdgeInsets.symmetric(vertical: 16),
              side: BorderSide(
                color: const Color(0xFFFBBF24).withValues(alpha: 0.5),
              ),
              foregroundColor: const Color(0xFFFBBF24),
              shape: RoundedRectangleBorder(
                borderRadius: BorderRadius.circular(14),
              ),
            ),
          ),
        ),
      ],
    );
  }
}

// ── Quick action buttons (Nova Tarefa & Nova Anotação) ──────────────────────

class _QuickActionButtons extends StatelessWidget {
  final VoidCallback onQuickTask;
  final VoidCallback onQuickNote;

  const _QuickActionButtons({
    required this.onQuickTask,
    required this.onQuickNote,
  });

  @override
  Widget build(BuildContext context) {
    return Row(
      children: [
        Expanded(
          child: FilledButton.icon(
            onPressed: onQuickTask,
            icon: const Icon(Icons.add_task, size: 20),
            label: const Text('Nova Tarefa'),
            style: FilledButton.styleFrom(
              padding: const EdgeInsets.symmetric(vertical: 14),
              backgroundColor: const Color(0xFFF59E0B),
              shape: RoundedRectangleBorder(
                borderRadius: BorderRadius.circular(14),
              ),
            ),
          ),
        ),
        const SizedBox(width: 12),
        Expanded(
          child: FilledButton.icon(
            onPressed: onQuickNote,
            icon: const Icon(Icons.note_add_outlined, size: 20),
            label: const Text('Nova Anotação'),
            style: FilledButton.styleFrom(
              padding: const EdgeInsets.symmetric(vertical: 14),
              backgroundColor: const Color(0xFF6366F1),
              shape: RoundedRectangleBorder(
                borderRadius: BorderRadius.circular(14),
              ),
            ),
          ),
        ),
      ],
    );
  }
}

// ── Quick note capture (modal) ───────────────────────────────────────────────

class _NoteQuickAddCard extends StatefulWidget {
  const _NoteQuickAddCard();

  @override
  State<_NoteQuickAddCard> createState() => _NoteQuickAddCardState();
}

class _NoteQuickAddCardState extends State<_NoteQuickAddCard> {
  final TextEditingController _titleController = TextEditingController();
  final TextEditingController _contentController = TextEditingController();
  String _category = 'geral';
  bool _saving = false;

  static const _categories = {
    'curso': ('Curso', Color(0xFF6366F1)),
    'ideia': ('Ideia', Color(0xFFFBBF24)),
    'curiosidade': ('Curiosidade', Color(0xFF22C55E)),
    'link': ('Link', Color(0xFF3B82F6)),
    'geral': ('Geral', Color(0xFF9CA3AF)),
    'lista': ('Lista', Color(0xFFF472B6)),
    'meta': ('Meta', Color(0xFFEF4444)),
  };

  @override
  void dispose() {
    _titleController.dispose();
    _contentController.dispose();
    super.dispose();
  }

  Future<void> _save() async {
    final title = _titleController.text.trim();
    final content = _contentController.text.trim();
    if (title.isEmpty && content.isEmpty) return;
    if (_saving) return;
    setState(() => _saving = true);

    try {
      final db = AppDatabase();
      final noteRepo = NoteRepository(db);
      await noteRepo.create(
        title: title,
        content: content,
        category: _category,
      );
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
          content: Text('Anotação salva!'),
          backgroundColor: Color(0xFF22C55E),
          behavior: SnackBarBehavior.floating,
        ),
      );
      Navigator.pop(context);
    } finally {
      if (mounted) setState(() => _saving = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.all(20),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              const Icon(
                Icons.note_add_outlined,
                color: Color(0xFF6366F1),
                size: 22,
              ),
              const SizedBox(width: 10),
              Text(
                'NOVA ANOTAÇÃO',
                style: TextStyle(
                  color: Colors.white.withValues(alpha: 0.9),
                  fontSize: 13,
                  fontWeight: FontWeight.w800,
                  letterSpacing: 1.5,
                ),
              ),
            ],
          ),
          const SizedBox(height: 16),
          TextField(
            controller: _titleController,
            textCapitalization: TextCapitalization.sentences,
            style: const TextStyle(color: Colors.white),
            decoration: const InputDecoration(
              hintText: 'Título',
              prefixIcon: Icon(Icons.title, color: Color(0xFF6366F1)),
            ),
          ),
          const SizedBox(height: 12),
          TextField(
            controller: _contentController,
            textCapitalization: TextCapitalization.sentences,
            maxLines: 3,
            style: const TextStyle(color: Colors.white),
            decoration: const InputDecoration(
              hintText: 'Conteúdo...',
              prefixIcon: Padding(
                padding: EdgeInsets.only(bottom: 48),
                child: Icon(Icons.notes, color: Color(0xFF6366F1)),
              ),
            ),
          ),
          const SizedBox(height: 12),
          Wrap(
            spacing: 8,
            runSpacing: 8,
            children: _categories.entries.map((e) {
              final selected = _category == e.key;
              final label = e.value.$1;
              final color = e.value.$2;
              return ChoiceChip(
                label: Text(label, style: TextStyle(fontSize: 12)),
                selected: selected,
                selectedColor: color.withValues(alpha: 0.3),
                backgroundColor: const Color(
                  0xFFFFFFFF,
                ).withValues(alpha: 0.06),
                side: BorderSide(
                  color: selected
                      ? color
                      : const Color(0xFFFFFFFF).withValues(alpha: 0.1),
                ),
                onSelected: (_) => setState(() => _category = e.key),
              );
            }).toList(),
          ),
          const SizedBox(height: 16),
          SizedBox(
            width: double.infinity,
            child: FilledButton.icon(
              onPressed: _saving ? null : _save,
              icon: _saving
                  ? const SizedBox(
                      width: 18,
                      height: 18,
                      child: CircularProgressIndicator(
                        strokeWidth: 2,
                        color: Colors.white,
                      ),
                    )
                  : const Icon(Icons.save_outlined),
              label: const Text('Salvar Anotação'),
              style: FilledButton.styleFrom(
                padding: const EdgeInsets.symmetric(vertical: 14),
              ),
            ),
          ),
        ],
      ),
    );
  }
}

// Helper widget for sync detail dialog
class _SyncDetailRow extends StatelessWidget {
  final IconData icon;
  final String label;
  final int count;
  final Color color;

  const _SyncDetailRow({
    required this.icon,
    required this.label,
    required this.count,
    required this.color,
  });

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 4),
      child: Row(
        children: [
          Icon(icon, color: color, size: 20),
          const SizedBox(width: 12),
          Expanded(
            child: Text(
              label,
              style: const TextStyle(color: Colors.white, fontSize: 14),
            ),
          ),
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
            decoration: BoxDecoration(
              color: color.withValues(alpha: 0.2),
              borderRadius: BorderRadius.circular(12),
            ),
            child: Text(
              count.toString(),
              style: TextStyle(
                color: color,
                fontWeight: FontWeight.w700,
                fontSize: 13,
              ),
            ),
          ),
        ],
      ),
    );
  }
}

// ── Pairing redirect (used after unpair) ─────────────────────────────────────

class _PairingRedirect extends StatelessWidget {
  const _PairingRedirect();

  @override
  Widget build(BuildContext context) {
    // Navigate to the pairing screen, clearing the entire navigation stack
    WidgetsBinding.instance.addPostFrameCallback((_) {
      Navigator.of(context).pushAndRemoveUntil(
        MaterialPageRoute(builder: (_) => const PairingScreen()),
        (route) => false,
      );
    });
    return const Scaffold(
      backgroundColor: Color(0xFF07090F),
      body: Center(child: CircularProgressIndicator(color: Color(0xFF6366F1))),
    );
  }
}

class _StatsRow extends StatelessWidget {
  final int pendingCount;
  final int failedCount;
  final int pendingNotesCount;
  final int pendingVisitsCount;
  final int totalPendingCount;
  final DateTime? lastSync;

  const _StatsRow({
    required this.pendingCount,
    required this.failedCount,
    required this.pendingNotesCount,
    required this.pendingVisitsCount,
    required this.totalPendingCount,
    this.lastSync,
  });

  @override
  Widget build(BuildContext context) {
    return Column(
      children: [
        Row(
          children: [
            Expanded(
              child: _StatCard(
                icon: Icons.pending_actions,
                label: 'Total Pendentes',
                value: totalPendingCount.toString(),
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
        ),
        const SizedBox(height: 8),
        Row(
          children: [
            Expanded(
              child: _StatCard(
                icon: Icons.sync,
                label: 'Comandos/Tarefas',
                value: pendingCount.toString(),
                color: const Color(0xFFF59E0B),
              ),
            ),
            const SizedBox(width: 12),
            Expanded(
              child: _StatCard(
                icon: Icons.note_alt_outlined,
                label: 'Anotações',
                value: pendingNotesCount.toString(),
                color: const Color(0xFF6366F1),
              ),
            ),
            const SizedBox(width: 12),
            Expanded(
              child: _StatCard(
                icon: Icons.place,
                label: 'Visitas',
                value: pendingVisitsCount.toString(),
                color: const Color(0xFF22C55E),
              ),
            ),
          ],
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
        border: Border.all(
          color: const Color(0xFFFFFFFF).withValues(alpha: 0.08),
        ),
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
          style: TextStyle(
            fontSize: 16,
            fontWeight: FontWeight.w600,
            color: Colors.white,
          ),
        ),
        const SizedBox(height: 12),
        if (commands.isEmpty)
          Container(
            padding: const EdgeInsets.all(24),
            decoration: BoxDecoration(
              color: const Color(0xFFFFFFFF).withValues(alpha: 0.04),
              border: Border.all(
                color: const Color(0xFFFFFFFF).withValues(alpha: 0.08),
              ),
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
        border: Border.all(
          color: const Color(0xFFFFFFFF).withValues(alpha: 0.08),
        ),
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
                  style: const TextStyle(
                    fontSize: 11,
                    color: Color(0xFF5E6A7E),
                  ),
                ),
              ],
            ),
          ),
          if (command.syncedAt != null)
            const Icon(Icons.check_circle, color: Color(0xFF22C55E), size: 20)
          else
            const Icon(
              Icons.hourglass_empty,
              color: Color(0xFFF59E0B),
              size: 20,
            ),
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
        border: Border.all(
          color: const Color(0xFFFFFFFF).withValues(alpha: 0.08),
        ),
        borderRadius: BorderRadius.circular(16),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          Row(
            children: [
              const Icon(
                Icons.info_outline,
                size: 18,
                color: Color(0xFF6366F1),
              ),
              const SizedBox(width: 8),
              const Text(
                'Última Sincronização',
                style: TextStyle(
                  fontSize: 14,
                  fontWeight: FontWeight.w600,
                  color: Colors.white,
                ),
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
                        const Icon(
                          Icons.error_outline,
                          size: 16,
                          color: Color(0xFFEF4444),
                        ),
                        const SizedBox(width: 8),
                        Expanded(
                          child: Text(
                            lastError!,
                            style: const TextStyle(
                              fontSize: 12,
                              color: Color(0xFFEF4444),
                            ),
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
        title: const Text(
          'Informações do Dispositivo',
          style: TextStyle(color: Colors.white),
        ),
        content: FutureBuilder<Map<String, dynamic>>(
          future: _getDeviceInfo(),
          builder: (ctx, snapshot) {
            if (!snapshot.hasData) {
              return const Center(
                child: CircularProgressIndicator(color: Color(0xFF6366F1)),
              );
            }
            final info = snapshot.data!;
            return Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.start,
              children: info.entries
                  .map((e) => _InfoRow(label: e.key, value: e.value))
                  .toList(),
            );
          },
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context),
            child: const Text(
              'Fechar',
              style: TextStyle(color: Color(0xFF6366F1)),
            ),
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
        title: const Text(
          'Desparear Dispositivo',
          style: TextStyle(color: Colors.white),
        ),
        content: const Text(
          'Isso removerá o pareamento com o PC. Você precisará escanear o QR code novamente para reconectar.',
          style: TextStyle(color: Color(0xFF9CA3AF)),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx),
            child: const Text(
              'Cancelar',
              style: TextStyle(color: Color(0xFF9CA3AF)),
            ),
          ),
          FilledButton(
            onPressed: () async {
              Navigator.pop(ctx);
              await DeviceIdentity.clearPairing();
              if (!context.mounted) return;
              ref.read(isPairedProvider.notifier).state = false;
              Navigator.of(context).pushAndRemoveUntil(
                MaterialPageRoute(builder: (_) => const _PairingRedirect()),
                (route) => false,
              );
            },
            style: FilledButton.styleFrom(
              backgroundColor: const Color(0xFFEF4444),
            ),
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
        title: const Text(
          'Limpar Dados Locais',
          style: TextStyle(color: Colors.white),
        ),
        content: const Text(
          'Isso removerá todo o banco de dados local (comandos, lugares, logs). O pareamento será mantido.',
          style: TextStyle(color: Color(0xFF9CA3AF)),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx),
            child: const Text(
              'Cancelar',
              style: TextStyle(color: Color(0xFF9CA3AF)),
            ),
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
            style: FilledButton.styleFrom(
              backgroundColor: const Color(0xFFF59E0B),
            ),
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
        child: Text(
          'Logs de debug - implementar',
          style: TextStyle(color: Color(0xFF5E6A7E)),
        ),
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
            child: Text(
              label,
              style: const TextStyle(color: Color(0xFF5E6A7E), fontSize: 13),
            ),
          ),
          Expanded(
            child: Text(
              value,
              style: const TextStyle(color: Colors.white, fontSize: 13),
            ),
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
  double _initProgress = 0;
  String _initPhase = '';
  bool _isBusy = false;
  bool _isDownloading = false;
  bool _isInitializing = false;
  String? _lastError;
  DateTime? _lastInitFailure;

  static const _prefsKeyLastInitFailure = 'gemma_last_init_failure';

  @override
  void initState() {
    super.initState();
    _loadLastInitFailure();
    // Auto-initialize if model already downloaded
    WidgetsBinding.instance.addPostFrameCallback((_) => _autoInit());
  }

  Future<void> _loadLastInitFailure() async {
    final prefs = await SharedPreferences.getInstance();
    final timestamp = prefs.getInt(_prefsKeyLastInitFailure);
    if (timestamp != null) {
      _lastInitFailure = DateTime.fromMillisecondsSinceEpoch(timestamp);
    }
  }

  Future<void> _saveLastInitFailure() async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setInt(
      _prefsKeyLastInitFailure,
      DateTime.now().millisecondsSinceEpoch,
    );
    _lastInitFailure = DateTime.now();
  }

  Future<void> _clearLastInitFailure() async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.remove(_prefsKeyLastInitFailure);
    _lastInitFailure = null;
  }

  Future<void> _autoInit() async {
    // Skip auto-init if failed recently (within 24 hours) to avoid repeated failures
    if (_lastInitFailure != null) {
      final hoursSinceFailure = DateTime.now()
          .difference(_lastInitFailure!)
          .inHours;
      if (hoursSinceFailure < 24) {
        return;
      }
    }

    final statusNotifier = ref.read(gemmaStatusProvider.notifier);
    // The settings tile is recreated whenever the settings modal is opened.
    // Keep the shared native session alive and only reflect its current state;
    // do not show an artificial initializing cycle on every visit.
    if (_aiService.isInitialized) {
      statusNotifier.set(GemmaStatus.ready);
      return;
    }
    final modelExists = await GemmaEngine.checkModelExists();
    if (modelExists) {
      statusNotifier.set(GemmaStatus.initializing);
      setState(() {
        _isBusy = true;
        _isInitializing = true;
        _initProgress = 0;
        _initPhase = 'model_loading';
      });
      final success = await _aiService.initialize(onProgress: _onInitProgress);
      statusNotifier.set(success ? GemmaStatus.ready : GemmaStatus.error);
      if (!success) {
        await _saveLastInitFailure();
      } else {
        await _clearLastInitFailure();
      }
      if (!success && mounted) {
        setState(() => _lastError = _aiService.lastError);
      }
      setState(() {
        _isBusy = false;
        _isInitializing = false;
      });
    }
  }

  void _onInitProgress(double progress, String phase) {
    if (!mounted) return;
    setState(() {
      _initProgress = progress;
      _initPhase = phase;
    });
  }

  Future<void> _checkAndInitialize() async {
    setState(() {
      _isBusy = true;
      _lastError = null;
    });

    final statusNotifier = ref.read(gemmaStatusProvider.notifier);

    if (_aiService.isInitialized) {
      statusNotifier.set(GemmaStatus.ready);
      setState(() => _isBusy = false);
      return;
    }

    final modelExists = await GemmaEngine.checkModelExists();
    if (!modelExists) {
      await _startAuthFlow();
      setState(() => _isBusy = false);
      return;
    }

    statusNotifier.set(GemmaStatus.initializing);
    setState(() {
      _isInitializing = true;
      _initProgress = 0;
      _initPhase = 'model_loading';
    });

    final success = await _aiService.initialize(onProgress: _onInitProgress);
    statusNotifier.set(success ? GemmaStatus.ready : GemmaStatus.error);
    if (!success) {
      await _saveLastInitFailure();
      if (mounted) {
        setState(() => _lastError = _aiService.lastError);
      }
    } else {
      await _clearLastInitFailure();
    }
    setState(() {
      _isBusy = false;
      _isInitializing = false;
    });
  }

  Future<void> _startAuthFlow() async {
    final result = await Navigator.push<Map<String, String>>(
      context,
      MaterialPageRoute(builder: (_) => const HfAuthWebView()),
    );

    final cookies = result?['cookies'] ?? '';
    final token = result?['token'] ?? '';

    if (cookies.isEmpty && token.isEmpty) {
      if (mounted) {
        ref.read(gemmaStatusProvider.notifier).set(GemmaStatus.error);
        setState(() {
          _isBusy = false;
          _lastError =
              'Autenticação cancelada ou falhou. Toque em "Baixar / Inicializar" para tentar novamente.';
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
    setState(() {
      _isDownloading = true;
      _downloadProgress = 0;
    });

    try {
      final success = await GemmaEngine.downloadWithCookies(
        cookies,
        token: token,
        onProgress: (p) {
          if (mounted) setState(() => _downloadProgress = p);
        },
      );

      if (success) {
        statusNotifier.set(GemmaStatus.initializing);
        setState(() {
          _isDownloading = false;
          _isInitializing = true;
          _initProgress = 0;
          _initPhase = 'model_loading';
        });

        final initSuccess = await _aiService.initialize(
          onProgress: _onInitProgress,
        );
        statusNotifier.set(initSuccess ? GemmaStatus.ready : GemmaStatus.error);
        if (!initSuccess) {
          await _saveLastInitFailure();
          if (mounted) {
            setState(() => _lastError = _aiService.lastError);
            ScaffoldMessenger.of(context).showSnackBar(
              SnackBar(
                content: Text(
                  _aiService.lastError ??
                      'Falha ao inicializar modelo. Tente novamente.',
                ),
                backgroundColor: Color(0xFFEF4444),
                duration: Duration(seconds: 5),
              ),
            );
          }
        } else {
          await _clearLastInitFailure();
        }
      } else {
        statusNotifier.set(GemmaStatus.error);
        if (mounted) {
          ScaffoldMessenger.of(context).showSnackBar(
            const SnackBar(
              content: Text(
                'Falha ao baixar modelo. Verifique conexão e tente novamente.',
              ),
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
    setState(() {
      _isBusy = false;
      _isDownloading = false;
      _isInitializing = false;
    });
  }

  Future<void> _shutdown() async {
    setState(() => _isBusy = true);
    await _aiService.shutdown();
    await _clearLastInitFailure();
    ref.read(gemmaStatusProvider.notifier).set(GemmaStatus.unchecked);
    setState(() {
      _isBusy = false;
      _downloadProgress = 0;
      _initProgress = 0;
      _initPhase = '';
      _lastError = null;
    });
  }

  String _getPhaseLabel(String phase) {
    switch (phase) {
      case 'model_loading':
        return 'Carregando pesos do modelo...';
      case 'session_creating':
        return 'Criando sessão de inferência...';
      case 'ready':
        return 'Pronto';
      default:
        return 'Inicializando...';
    }
  }

  Color _getPhaseColor(String phase) {
    switch (phase) {
      case 'model_loading':
        return const Color(0xFF6366F1);
      case 'session_creating':
        return const Color(0xFFF59E0B);
      case 'ready':
        return const Color(0xFF22C55E);
      default:
        return const Color(0xFF6366F1);
    }
  }

  String _formatFailureTime(DateTime dt) {
    final now = DateTime.now();
    final diff = now.difference(dt);
    if (diff.inMinutes < 1) return 'agora mesmo';
    if (diff.inMinutes < 60) return 'há ${diff.inMinutes} min';
    if (diff.inHours < 24) return 'há ${diff.inHours}h';
    return 'há ${diff.inDays}d';
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
                const Icon(
                  Icons.psychology,
                  color: Color(0xFF6366F1),
                  size: 24,
                ),
                const SizedBox(width: 12),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      const Text(
                        'Modelo: Gemma 3 1B',
                        style: TextStyle(
                          color: Colors.white,
                          fontSize: 14,
                          fontWeight: FontWeight.w500,
                        ),
                      ),
                      const SizedBox(height: 2),
                      Text(
                        statusNotifier.label,
                        style: TextStyle(
                          color: status == GemmaStatus.ready
                              ? const Color(0xFF22C55E)
                              : status == GemmaStatus.error ||
                                    status == GemmaStatus.unavailable
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
                else if (status == GemmaStatus.initializing)
                  SizedBox(
                    width: 24,
                    height: 24,
                    child: CircularProgressIndicator(
                      value: _initProgress > 0 ? _initProgress : null,
                      strokeWidth: 2,
                      color: _getPhaseColor(_initPhase),
                    ),
                  )
                else if (status == GemmaStatus.ready)
                  const Icon(
                    Icons.check_circle,
                    color: Color(0xFF22C55E),
                    size: 22,
                  )
                else if (status == GemmaStatus.error ||
                    status == GemmaStatus.unavailable)
                  const Icon(
                    Icons.error_outline,
                    color: Color(0xFFEF4444),
                    size: 22,
                  ),
              ],
            ),
            if (_isDownloading) ...[
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
                'Baixando modelo: ${(_downloadProgress * 100).toStringAsFixed(0)}% (658 MB)',
                style: const TextStyle(color: Color(0xFF5E6A7E), fontSize: 11),
              ),
            ],
            if (_isInitializing) ...[
              const SizedBox(height: 8),
              ClipRRect(
                borderRadius: BorderRadius.circular(4),
                child: LinearProgressIndicator(
                  value: _initProgress > 0 ? _initProgress : null,
                  backgroundColor: const Color(0xFF1E293B),
                  valueColor: AlwaysStoppedAnimation(
                    _getPhaseColor(_initPhase),
                  ),
                  minHeight: 4,
                ),
              ),
              const SizedBox(height: 4),
              Row(
                mainAxisAlignment: MainAxisAlignment.spaceBetween,
                children: [
                  Text(
                    _getPhaseLabel(_initPhase),
                    style: TextStyle(
                      color: _getPhaseColor(_initPhase),
                      fontSize: 11,
                      fontWeight: FontWeight.w500,
                    ),
                  ),
                  TextButton(
                    onPressed: _shutdown,
                    style: TextButton.styleFrom(
                      padding: EdgeInsets.zero,
                      minimumSize: const Size(0, 28),
                      tapTargetSize: MaterialTapTargetSize.shrinkWrap,
                      foregroundColor: const Color(0xFFEF4444),
                    ),
                    child: const Text(
                      'Cancelar',
                      style: TextStyle(fontSize: 11),
                    ),
                  ),
                ],
              ),
            ],
            const SizedBox(height: 8),
            if (status == GemmaStatus.error && _lastError != null) ...[
              Container(
                padding: const EdgeInsets.all(10),
                decoration: BoxDecoration(
                  color: const Color(0xFFEF4444).withValues(alpha: 0.15),
                  borderRadius: BorderRadius.circular(8),
                  border: Border.all(
                    color: const Color(0xFFEF4444).withValues(alpha: 0.3),
                  ),
                ),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Row(
                      children: [
                        const Icon(
                          Icons.error_outline,
                          color: Color(0xFFEF4444),
                          size: 16,
                        ),
                        const SizedBox(width: 8),
                        Expanded(
                          child: Text(
                            _lastError!,
                            style: const TextStyle(
                              color: Color(0xFFEF4444),
                              fontSize: 11,
                            ),
                          ),
                        ),
                        TextButton(
                          onPressed: _isBusy
                              ? null
                              : () => _checkAndInitialize(),
                          style: TextButton.styleFrom(
                            padding: EdgeInsets.zero,
                            minimumSize: const Size(0, 28),
                            tapTargetSize: MaterialTapTargetSize.shrinkWrap,
                          ),
                          child: const Text(
                            'Tentar novamente',
                            style: TextStyle(
                              fontSize: 11,
                              color: Color(0xFF6366F1),
                            ),
                          ),
                        ),
                      ],
                    ),
                    if (_lastInitFailure != null) ...[
                      const SizedBox(height: 4),
                      Text(
                        'Última falha: ${_formatFailureTime(_lastInitFailure!)}',
                        style: const TextStyle(
                          color: Color(0xFF9CA3AF),
                          fontSize: 10,
                        ),
                      ),
                    ],
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
                    label: const Text(
                      'Descarregar',
                      style: TextStyle(fontSize: 12),
                    ),
                    style: TextButton.styleFrom(
                      foregroundColor: const Color(0xFFEF4444),
                    ),
                  )
                else if (!_isDownloading && !_isInitializing)
                  TextButton.icon(
                    onPressed: _isBusy ? null : _checkAndInitialize,
                    icon: Icon(
                      Icons.download,
                      size: 16,
                      color: _isBusy
                          ? const Color(0xFF5E6A7E)
                          : const Color(0xFF6366F1),
                    ),
                    label: Text(
                      _isBusy ? 'Verificando...' : 'Baixar / Inicializar',
                      style: TextStyle(
                        fontSize: 12,
                        color: _isBusy
                            ? const Color(0xFF5E6A7E)
                            : const Color(0xFF6366F1),
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
      leading: Icon(
        icon,
        color: iconColor ?? const Color(0xFF6366F1),
        size: 24,
      ),
      title: Text(
        title,
        style: TextStyle(
          color: textColor ?? Colors.white,
          fontSize: 15,
          fontWeight: FontWeight.w500,
        ),
      ),
      subtitle: Text(
        subtitle,
        style: const TextStyle(color: Color(0xFF5E6A7E), fontSize: 12),
      ),
      trailing: Icon(trailingIcon, color: const Color(0xFF5E6A7E), size: 20),
      onTap: onTap,
      contentPadding: const EdgeInsets.symmetric(horizontal: 4),
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
      tileColor: const Color(0xFFFFFFFF).withValues(alpha: 0.03),
    );
  }
}

// ── Quick task capture ────────────────────────────────────────────────────────
//
// Moved to features/tasks/presentation/create_task_screen.dart

class _UpcomingTasksSection extends StatelessWidget {
  final int tick;
  final VoidCallback onChanged;

  const _UpcomingTasksSection({required this.tick, required this.onChanged});

  String _formatDate(DateTime d) {
    final now = DateTime.now();
    final today = DateTime(now.year, now.month, now.day);
    final target = DateTime(d.year, d.month, d.day);
    final diff = target.difference(today).inDays;
    if (diff == 0) return 'Hoje';
    if (diff == 1) return 'Amanhã';
    return '${d.day.toString().padLeft(2, '0')}/${d.month.toString().padLeft(2, '0')}';
  }

  String _dueLabel(ScheduledTask task) {
    if (task.isDateRange) {
      if (task.startDate == null || task.endDate == null) return 'sem data';
      final start = task.startDate!;
      final end = task.endDate!;
      final startFmt = _formatDate(start);
      final endFmt = _formatDate(end);
      if (startFmt == endFmt) {
        return '$startFmt';
      }
      return '$startFmt a $endFmt';
    }
    final t = task.dueAt;
    if (t == null) return 'sem data';
    final diff = t.difference(DateTime.now());
    if (diff.isNegative) return 'agora';
    if (diff.inMinutes < 60) return 'em ${diff.inMinutes} min';
    if (diff.inHours < 24) return 'em ${(diff.inMinutes / 60).round()} h';
    return '${_formatDate(t)} ${t.hour.toString().padLeft(2, '0')}:${t.minute.toString().padLeft(2, '0')}';
  }

  @override
  Widget build(BuildContext context) {
    return StreamBuilder<List<ScheduledTask>>(
      key: ValueKey(tick),
      stream: TaskAlarmService.watchPendingTasks(),
      builder: (context, snapshot) {
        final tasks = snapshot.data ?? [];
        if (tasks.isEmpty) {
          return const _SectionTitle('PRÓXIMAS TAREFAS');
        }
        return Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const _SectionTitle('PRÓXIMAS TAREFAS'),
            ...tasks
                .take(5)
                .map(
                  (task) => Card(
                    margin: const EdgeInsets.only(bottom: 8),
                    child: ListTile(
                      leading: Icon(
                        task.dueAt?.isBefore(DateTime.now()) ?? false
                            ? Icons.notifications_active_rounded
                            : Icons.alarm_rounded,
                        color: task.dueAt?.isBefore(DateTime.now()) ?? false
                            ? const Color(0xFFEF4444)
                            : const Color(0xFF6366F1),
                      ),
                      title: Text(
                        task.title,
                        maxLines: 2,
                        overflow: TextOverflow.ellipsis,
                        style: const TextStyle(
                          color: Colors.white,
                          fontSize: 14,
                          fontWeight: FontWeight.w600,
                        ),
                      ),
                      subtitle: Text(
                        _dueLabel(task),
                        style: const TextStyle(
                          color: Color(0xFF9CA3AF),
                          fontSize: 12,
                        ),
                      ),
                      trailing: IconButton(
                        icon: const Icon(
                          Icons.check_circle_outline_rounded,
                          color: Color(0xFF22C55E),
                        ),
                        tooltip: 'Concluir',
                        onPressed: () async {
                          await TaskAlarmService.markDone(task.remoteId);
                          onChanged();
                        },
                      ),
                    ),
                  ),
                ),
          ],
        );
      },
    );
  }
}
