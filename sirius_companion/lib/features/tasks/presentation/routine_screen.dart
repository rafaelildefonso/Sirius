import 'package:flutter/material.dart';
import '../../../core/storage/database/database.dart';
import '../routine_service.dart';

class RoutineScreen extends StatefulWidget {
  const RoutineScreen({super.key});

  @override
  State<RoutineScreen> createState() => _RoutineScreenState();
}

class _RoutineScreenState extends State<RoutineScreen> {
  DateTime _week = _weekStart(DateTime.now());
  int _refresh = 0;

  static DateTime _weekStart(DateTime day) =>
      DateTime(day.year, day.month, day.day - day.weekday % 7);

  Future<void> _reload() async {
    await RoutineService.generateUpcomingOccurrences();
    if (mounted) setState(() => _refresh++);
  }

  Future<void> _moveWeek(int days) async {
    final next = _week.add(Duration(days: days));
    setState(() => _week = next);
    await RoutineService.generateUpcomingOccurrences(now: next);
    if (mounted) setState(() => _refresh++);
  }

  Future<void> _edit([Map<String, dynamic>? routine]) async {
    final result = await showDialog<Map<String, dynamic>>(
      context: context,
      builder: (_) => _RoutineDialog(routine: routine),
    );
    if (result == null) return;
    if (routine == null) {
      final (_, error) = await RoutineService.create(result);
      if (error != null && mounted) _message(error);
    } else {
      await RoutineService.update(routine['id'] as String, result);
    }
    await _reload();
  }

  void _message(String text) =>
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(text)));

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('Rotina'),
        actions: [
          IconButton(
            onPressed: () => _edit(),
            icon: const Icon(Icons.add),
            tooltip: 'Novo hábito',
          ),
          IconButton(
            onPressed: _reload,
            icon: const Icon(Icons.refresh),
            tooltip: 'Atualizar',
          ),
        ],
      ),
      body: FutureBuilder<List<dynamic>>(
        key: ValueKey(_refresh),
        future: Future.wait([
          RoutineService.list(),
          RoutineService.occurrences(_week, 7),
        ]),
        builder: (context, snapshot) {
          if (snapshot.hasError) {
            return Center(
              child: Column(
                mainAxisSize: MainAxisSize.min,
                children: [
                  const Text('Não foi possível carregar sua rotina.'),
                  TextButton(
                    onPressed: _reload,
                    child: const Text('Tentar novamente'),
                  ),
                ],
              ),
            );
          }
          if (!snapshot.hasData)
            return const Center(child: CircularProgressIndicator());
          final routines =
              snapshot.data?[0] as List<Map<String, dynamic>>? ?? [];
          final occurrences = snapshot.data?[1] as List<ScheduledTask>? ?? [];
          return ListView(
            padding: const EdgeInsets.all(16),
            children: [
              Row(
                children: [
                  IconButton(
                    onPressed: () => _moveWeek(-7),
                    icon: const Icon(Icons.chevron_left),
                  ),
                  Expanded(
                    child: Center(
                      child: Text(
                        '${_date(_week)} – ${_date(_week.add(const Duration(days: 6)))}',
                        style: const TextStyle(fontWeight: FontWeight.w600),
                      ),
                    ),
                  ),
                  IconButton(
                    onPressed: () => _moveWeek(7),
                    icon: const Icon(Icons.chevron_right),
                  ),
                ],
              ),
              for (var i = 0; i < 7; i++)
                _dayCard(_week.add(Duration(days: i)), occurrences),
              const SizedBox(height: 20),
              const Text(
                'Hábitos cadastrados',
                style: TextStyle(fontSize: 18, fontWeight: FontWeight.bold),
              ),
              const SizedBox(height: 8),
              if (routines.isEmpty)
                const Text(
                  'Adicione um hábito para começar sua rotina semanal.',
                ),
              for (final routine in routines) _routineTile(routine),
            ],
          );
        },
      ),
    );
  }

  Widget _dayCard(DateTime date, List<ScheduledTask> occurrences) {
    final entries = occurrences.where((task) {
      final due = task.dueAt?.toLocal();
      return due != null &&
          due.year == date.year &&
          due.month == date.month &&
          due.day == date.day;
    }).toList();
    final today = DateTime.now();
    final isToday =
        today.year == date.year &&
        today.month == date.month &&
        today.day == date.day;
    return Card(
      color: isToday ? const Color(0xFF192044) : null,
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              '${RoutineService.weekdays[date.weekday % 7]}  ${_date(date)}',
              style: const TextStyle(fontWeight: FontWeight.bold),
            ),
            if (entries.isEmpty)
              const Padding(
                padding: EdgeInsets.only(top: 8),
                child: Text(
                  'Sem hábitos programados',
                  style: TextStyle(color: Colors.white54),
                ),
              ),
            for (final task in entries)
              ListTile(
                contentPadding: EdgeInsets.zero,
                leading: Icon(
                  task.status == 'done'
                      ? Icons.check_circle
                      : Icons.circle_outlined,
                  color: task.status == 'done' ? Colors.greenAccent : null,
                ),
                title: Text(
                  task.title,
                  style: TextStyle(
                    decoration: task.status == 'done'
                        ? TextDecoration.lineThrough
                        : null,
                  ),
                ),
                subtitle: Text(
                  '${_time(task.dueAt!)}${task.status == 'done' ? ' · Concluído' : ''}',
                ),
                trailing: task.status == 'done'
                    ? const Icon(Icons.done, color: Colors.greenAccent)
                    : IconButton(
                        icon: const Icon(Icons.check),
                        tooltip: 'Concluir ocorrência',
                        onPressed: () async {
                          await RoutineService.complete(task.remoteId);
                          await _reload();
                        },
                      ),
              ),
          ],
        ),
      ),
    );
  }

  Widget _routineTile(Map<String, dynamic> routine) {
    final days = (routine['weekdays'] as List)
        .cast<num>()
        .map((d) => RoutineService.weekdays[d.toInt()])
        .join(', ');
    final enabled = routine['enabled'] == true;
    return Card(
      child: ListTile(
        title: Text(routine['name'] as String),
        subtitle: Text(
          '${routine['time']} · $days · ${_modeName(routine['alert_mode'] as String)}${enabled ? '' : ' · Pausado'}',
        ),
        leading: Icon(enabled ? Icons.repeat : Icons.pause_circle_outline),
        onTap: () => _edit(routine),
        trailing: PopupMenuButton<String>(
          onSelected: (value) async {
            if (value == 'toggle')
              await RoutineService.setEnabled(
                routine['id'] as String,
                !enabled,
              );
            if (value == 'edit') await _edit(routine);
            if (value == 'delete') {
              if (!mounted) return;
              final confirmed = await showDialog<bool>(
                context: context,
                builder: (ctx) => AlertDialog(
                  title: const Text('Excluir hábito?'),
                  content: const Text(
                    'As próximas ocorrências serão removidas. O histórico concluído será mantido.',
                  ),
                  actions: [
                    TextButton(
                      onPressed: () => Navigator.pop(ctx, false),
                      child: const Text('Cancelar'),
                    ),
                    FilledButton(
                      onPressed: () => Navigator.pop(ctx, true),
                      child: const Text('Excluir'),
                    ),
                  ],
                ),
              );
              if (confirmed != true) return;
              await RoutineService.delete(routine['id'] as String);
              _message('Hábito excluído. O histórico concluído foi mantido.');
            }
            await _reload();
          },
          itemBuilder: (_) => [
            PopupMenuItem(
              value: 'toggle',
              child: Text(enabled ? 'Pausar' : 'Retomar'),
            ),
            const PopupMenuItem(value: 'edit', child: Text('Editar')),
            const PopupMenuItem(value: 'delete', child: Text('Excluir')),
          ],
        ),
      ),
    );
  }

  static String _date(DateTime d) =>
      '${d.day.toString().padLeft(2, '0')}/${d.month.toString().padLeft(2, '0')}';
  static String _time(DateTime d) =>
      '${d.hour.toString().padLeft(2, '0')}:${d.minute.toString().padLeft(2, '0')}';
  static String _modeName(String mode) => switch (mode) {
    'none' => 'Sem notificação',
    'notification' => 'Notificação',
    'alarm' => 'Alarme',
    'call' => 'Ligação do Sirius',
    _ => mode,
  };
}

class _RoutineDialog extends StatefulWidget {
  final Map<String, dynamic>? routine;
  const _RoutineDialog({this.routine});
  @override
  State<_RoutineDialog> createState() => _RoutineDialogState();
}

class _RoutineDialogState extends State<_RoutineDialog> {
  late final TextEditingController _name;
  late TimeOfDay _time;
  late Set<int> _days;
  late String _mode;

  @override
  void initState() {
    super.initState();
    final rec = widget.routine;
    _name = TextEditingController(text: rec?['name'] as String? ?? '');
    final parts = (rec?['time'] as String? ?? '09:00').split(':');
    _time = TimeOfDay(hour: int.parse(parts[0]), minute: int.parse(parts[1]));
    _days = (rec?['weekdays'] as List? ?? [])
        .whereType<num>()
        .map((v) => v.toInt())
        .toSet();
    _mode = rec?['alert_mode'] as String? ?? 'none';
  }

  @override
  Widget build(BuildContext context) => AlertDialog(
    title: Text(widget.routine == null ? 'Novo hábito' : 'Editar hábito'),
    content: SingleChildScrollView(
      child: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          TextField(
            controller: _name,
            autofocus: true,
            decoration: const InputDecoration(labelText: 'Nome do hábito'),
          ),
          const SizedBox(height: 12),
          OutlinedButton.icon(
            onPressed: () async {
              final selected = await showTimePicker(
                context: context,
                initialTime: _time,
              );
              if (selected != null) setState(() => _time = selected);
            },
            icon: const Icon(Icons.schedule),
            label: Text('Horário ${_time.format(context)}'),
          ),
          const SizedBox(height: 12),
          const Text('Dias da semana'),
          Wrap(
            spacing: 4,
            children: [
              for (var i = 0; i < 7; i++)
                FilterChip(
                  label: Text(RoutineService.weekdays[i]),
                  selected: _days.contains(i),
                  onSelected: (yes) =>
                      setState(() => yes ? _days.add(i) : _days.remove(i)),
                ),
            ],
          ),
          const SizedBox(height: 12),
          DropdownButtonFormField<String>(
            value: _mode,
            decoration: const InputDecoration(labelText: 'Aviso'),
            items: const [
              DropdownMenuItem(value: 'none', child: Text('Sem notificação')),
              DropdownMenuItem(
                value: 'notification',
                child: Text('Notificação'),
              ),
              DropdownMenuItem(value: 'alarm', child: Text('Alarme')),
              DropdownMenuItem(value: 'call', child: Text('Ligação do Sirius')),
            ],
            onChanged: (value) => setState(() => _mode = value ?? 'none'),
          ),
        ],
      ),
    ),
    actions: [
      TextButton(
        onPressed: () => Navigator.pop(context),
        child: const Text('Cancelar'),
      ),
      FilledButton(
        onPressed: () {
          if (_name.text.trim().isEmpty || _days.isEmpty) return;
          Navigator.pop(context, {
            'name': _name.text,
            'time':
                '${_time.hour.toString().padLeft(2, '0')}:${_time.minute.toString().padLeft(2, '0')}',
            'weekdays': _days.toList()..sort(),
            'alert_mode': _mode,
          });
        },
        child: const Text('Salvar'),
      ),
    ],
  );

  @override
  void dispose() {
    _name.dispose();
    super.dispose();
  }
}
