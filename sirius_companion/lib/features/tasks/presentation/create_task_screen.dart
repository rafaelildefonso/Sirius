import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../task_alarm_service.dart';
import '../recurring_task_service.dart';
import '../simulated_call_policy.dart';

/// Full-screen task creation with support for:
/// - Date-range tasks (mandatory start/end dates, optional time)
/// - Time-specific tasks (single due date/time)
/// - Recurring tasks ("Repetir" toggle -> recurrence options; a definition is
///   stored locally and scheduled on the phone without requiring the PC)
class CreateTaskScreen extends ConsumerStatefulWidget {
  const CreateTaskScreen({super.key});

  @override
  ConsumerState<CreateTaskScreen> createState() => _CreateTaskScreenState();
}

class _CreateTaskScreenState extends ConsumerState<CreateTaskScreen> {
  final TextEditingController _titleController = TextEditingController();
  final TextEditingController _notesController = TextEditingController();

  // Date-range mode
  DateTime? _startDate;
  DateTime? _endDate;

  // Time-specific mode
  DateTime? _dueAt;

  bool _isDateRangeMode = false;
  bool _siriusCallEnabled = false;
  String _callCapabilityHint =
      'A chamada abre no app; se a tela cheia estiver indisponível, chega uma notificação para tocar.';
  bool _dndAccessGranted = false;
  bool _saving = false;

  // Recurring mode ("Repetir" toggle)
  bool _repeat = false;
  String _repeatType = 'daily'; // daily | weekly | interval | monthly
  final Set<int> _repeatWeekdays = <int>{}; // 0=Mon .. 6=Sun
  int _repeatIntervalDays = 3;
  int _repeatMonthDay = 1;
  TimeOfDay _repeatTime = const TimeOfDay(hour: 9, minute: 0);
  int _repeatPeriodDays = 1;

  @override
  void initState() {
    super.initState();
    TaskAlarmService.getAlertCapabilities().then((capabilities) {
      if (!mounted) return;
      setState(() {
        _dndAccessGranted = capabilities['dndAccess'] == true;
        _callCapabilityHint = SimulatedCallPolicy.alertCapabilityHint(
          capabilities,
        );
      });
    });
  }

  @override
  void dispose() {
    _titleController.dispose();
    _notesController.dispose();
    super.dispose();
  }

  Future<void> _pickStartDate() async {
    final now = DateTime.now();
    final date = await showDatePicker(
      context: context,
      initialDate: _startDate ?? now,
      firstDate: now,
      lastDate: now.add(const Duration(days: 365 * 2)),
    );
    if (date == null) return;
    setState(() {
      _startDate = DateTime(date.year, date.month, date.day);
      _endDate = _startDate;
    });
  }

  Future<void> _pickEndDate() async {
    if (_startDate == null) {
      await _pickStartDate();
      if (_startDate == null) return;
    }
    final date = await showDatePicker(
      context: context,
      initialDate: _endDate ?? _startDate!,
      firstDate: _startDate!,
      lastDate: _startDate!.add(const Duration(days: 365 * 2)),
    );
    if (date == null) return;
    setState(() {
      _endDate = DateTime(date.year, date.month, date.day);
    });
  }

  Future<void> _pickDueDate() async {
    final now = DateTime.now();
    final date = await showDatePicker(
      context: context,
      initialDate: _dueAt ?? now,
      firstDate: now,
      lastDate: now.add(const Duration(days: 365 * 2)),
    );
    if (date == null) return;
    setState(() {
      _dueAt = DateTime(
        date.year,
        date.month,
        date.day,
        _dueAt?.hour ?? 9,
        _dueAt?.minute ?? 0,
      );
    });
  }

  Future<void> _pickDueTime() async {
    final base = _dueAt ?? DateTime.now().add(const Duration(hours: 1));
    final time = await showTimePicker(
      context: context,
      initialTime: TimeOfDay.fromDateTime(base),
    );
    if (time == null) return;
    final picked = DateTime(
      base.year,
      base.month,
      base.day,
      time.hour,
      time.minute,
    );
    setState(() {
      _dueAt = picked.isBefore(DateTime.now())
          ? picked.add(const Duration(days: 1))
          : picked;
    });
  }

  String _formatDate(DateTime d) {
    final now = DateTime.now();
    final today = DateTime(now.year, now.month, now.day);
    final target = DateTime(d.year, d.month, d.day);
    final diff = target.difference(today).inDays;
    if (diff == 0) return 'Hoje';
    if (diff == 1) return 'Amanhã';
    return '${d.day.toString().padLeft(2, '0')}/${d.month.toString().padLeft(2, '0')}';
  }

  String _formatDateTime(DateTime d) {
    return '${_formatDate(d)} ${d.hour.toString().padLeft(2, '0')}:${d.minute.toString().padLeft(2, '0')}';
  }

  Future<void> _pickRepeatTime() async {
    final time = await showTimePicker(
      context: context,
      initialTime: _repeatTime,
    );
    if (time != null) setState(() => _repeatTime = time);
  }

  String get _repeatTimeLabel =>
      '${_repeatTime.hour.toString().padLeft(2, '0')}:${_repeatTime.minute.toString().padLeft(2, '0')}';

  String _repeatSummary() {
    final schedule = switch (_repeatType) {
      'daily' => 'todos os dias',
      'weekly' =>
        _repeatWeekdays.isEmpty
            ? 'dias da semana'
            : _repeatWeekdays
                  .map((d) => RecurringTaskService.weekdayShort[d])
                  .join(', '),
      'interval' =>
        'a cada $_repeatIntervalDays dia${_repeatIntervalDays > 1 ? 's' : ''}',
      _ => 'todo dia $_repeatMonthDay do mês',
    };
    if (_isDateRangeMode)
      return '$schedule, período de $_repeatPeriodDays dia(s)';
    return '$schedule, às $_repeatTimeLabel';
  }

  /// Stores the definition locally, schedules today's occurrence and queues a
  /// copy for the PC to mirror when connectivity is available.
  Future<bool> _saveRecurring(String title, String notes) async {
    if (_repeatType == 'weekly' && _repeatWeekdays.isEmpty) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
          content: Text('Escolha pelo menos um dia da semana'),
          backgroundColor: Color(0xFFEF4444),
        ),
      );
      return false;
    }

    final payload = <String, dynamic>{
      'title': title,
      'recurrence_type': _repeatType,
      'sirius_call_enabled': !_isDateRangeMode && _siriusCallEnabled,
      if (_repeatType == 'weekly') 'weekdays': _repeatWeekdays.toList()..sort(),
      if (_repeatType == 'interval') 'interval_days': _repeatIntervalDays,
      if (_repeatType == 'monthly') 'month_day': _repeatMonthDay,
      if (notes.isNotEmpty) 'notes': notes,
    };
    if (_isDateRangeMode) {
      payload['period_days'] = _repeatPeriodDays;
    } else {
      payload['time_of_day'] = _repeatTimeLabel;
    }

    setState(() => _saving = true);
    try {
      final (rec, error) = await RecurringTaskService.create(payload);
      if (!mounted) return false;
      if (rec == null) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text(error ?? 'Erro ao criar recorrência'),
            backgroundColor: const Color(0xFFEF4444),
          ),
        );
        return false;
      }
      final next = RecurringTaskService.nextLabel(rec);
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text(
            'Recorrência criada (${_repeatSummary()})'
            '${next != null ? ' — próxima: $next' : ''} no celular',
          ),
          backgroundColor: const Color(0xFF22C55E),
          behavior: SnackBarBehavior.floating,
        ),
      );
      return true;
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text('Não foi possível salvar recorrência: $e'),
            backgroundColor: const Color(0xFFEF4444),
          ),
        );
      }
      return false;
    } finally {
      if (mounted) setState(() => _saving = false);
    }
  }

  /// The panel shown when "Repetir automaticamente" is on: how often the task
  /// regenerates (daily / weekdays / every N days / monthly) and whether each
  /// occurrence is a timed alarm or a date-range period.
  List<Widget> _buildRecurrenceOptions() {
    return [
      const SizedBox(height: 24),
      const Text(
        'REPETE COMO?',
        style: TextStyle(
          color: Color(0xFF22C55E),
          fontSize: 12,
          fontWeight: FontWeight.w700,
          letterSpacing: 1,
        ),
      ),
      const SizedBox(height: 12),
      Wrap(
        spacing: 8,
        runSpacing: 8,
        children: [
          _OptionChip(
            label: 'Todo dia',
            icon: Icons.today_rounded,
            selected: _repeatType == 'daily',
            color: const Color(0xFF22C55E),
            onTap: () => setState(() => _repeatType = 'daily'),
          ),
          _OptionChip(
            label: 'Semana',
            icon: Icons.view_week_rounded,
            selected: _repeatType == 'weekly',
            color: const Color(0xFF22C55E),
            onTap: () => setState(() => _repeatType = 'weekly'),
          ),
          _OptionChip(
            label: 'A cada X dias',
            icon: Icons.av_timer_rounded,
            selected: _repeatType == 'interval',
            color: const Color(0xFF22C55E),
            onTap: () => setState(() => _repeatType = 'interval'),
          ),
          _OptionChip(
            label: 'Mensal',
            icon: Icons.calendar_month_rounded,
            selected: _repeatType == 'monthly',
            color: const Color(0xFF22C55E),
            onTap: () => setState(() => _repeatType = 'monthly'),
          ),
        ],
      ),

      // Weekly: weekday picker (0=Seg .. 6=Dom)
      if (_repeatType == 'weekly') ...[
        const SizedBox(height: 20),
        const Text(
          'DIAS DA SEMANA',
          style: TextStyle(
            color: Color(0xFF9CA3AF),
            fontSize: 12,
            fontWeight: FontWeight.w700,
            letterSpacing: 1,
          ),
        ),
        const SizedBox(height: 10),
        Row(
          children: List.generate(7, (i) {
            final selected = _repeatWeekdays.contains(i);
            return Expanded(
              child: Padding(
                padding: EdgeInsets.only(left: i > 0 ? 6 : 0),
                child: _WeekdayChip(
                  label: RecurringTaskService.weekdayShort[i],
                  selected: selected,
                  onTap: () => setState(() {
                    if (selected) {
                      _repeatWeekdays.remove(i);
                    } else {
                      _repeatWeekdays.add(i);
                    }
                  }),
                ),
              ),
            );
          }),
        ),
      ],

      // Interval: every N days
      if (_repeatType == 'interval') ...[
        const SizedBox(height: 20),
        const Text(
          'DE QUANTO EM QUANTO TEMPO',
          style: TextStyle(
            color: Color(0xFF9CA3AF),
            fontSize: 12,
            fontWeight: FontWeight.w700,
            letterSpacing: 1,
          ),
        ),
        const SizedBox(height: 8),
        _NumberStepper(
          value: _repeatIntervalDays,
          min: 1,
          max: 365,
          suffix: 'dia(s)',
          onChanged: (v) => setState(() => _repeatIntervalDays = v),
        ),
      ],

      // Monthly: day of month
      if (_repeatType == 'monthly') ...[
        const SizedBox(height: 20),
        const Text(
          'DIA DO MÊS',
          style: TextStyle(
            color: Color(0xFF9CA3AF),
            fontSize: 12,
            fontWeight: FontWeight.w700,
            letterSpacing: 1,
          ),
        ),
        const SizedBox(height: 8),
        _NumberStepper(
          value: _repeatMonthDay,
          min: 1,
          max: 31,
          suffix: 'do mês',
          onChanged: (v) => setState(() => _repeatMonthDay = v),
        ),
      ],

      const SizedBox(height: 20),
      const Text(
        'CADA OCORRÊNCIA É',
        style: TextStyle(
          color: Color(0xFF9CA3AF),
          fontSize: 12,
          fontWeight: FontWeight.w700,
          letterSpacing: 1,
        ),
      ),
      const SizedBox(height: 10),
      Row(
        children: [
          Expanded(
            child: _OptionChip(
              label: 'Horário',
              icon: Icons.schedule,
              selected: !_isDateRangeMode,
              color: const Color(0xFF6366F1),
              onTap: () => setState(() => _isDateRangeMode = false),
            ),
          ),
          const SizedBox(width: 8),
          Expanded(
            child: _OptionChip(
              label: 'Período',
              icon: Icons.date_range,
              selected: _isDateRangeMode,
              color: const Color(0xFFF59E0B),
              onTap: () => setState(() => _isDateRangeMode = true),
            ),
          ),
        ],
      ),
      const SizedBox(height: 12),
      if (!_isDateRangeMode)
        // Timed occurrence: pick the alarm time (defaults 09:00)
        InkWell(
          onTap: _pickRepeatTime,
          borderRadius: BorderRadius.circular(12),
          child: Container(
            padding: const EdgeInsets.symmetric(vertical: 14, horizontal: 16),
            decoration: BoxDecoration(
              color: const Color(0xFFFFFFFF).withValues(alpha: 0.06),
              borderRadius: BorderRadius.circular(12),
              border: Border.all(color: const Color(0xFF6366F1), width: 1),
            ),
            child: Row(
              children: [
                const Icon(
                  Icons.alarm_rounded,
                  size: 18,
                  color: Color(0xFF6366F1),
                ),
                const SizedBox(width: 8),
                Expanded(
                  child: Text(
                    'Alarme às $_repeatTimeLabel',
                    style: const TextStyle(
                      color: Colors.white,
                      fontWeight: FontWeight.w600,
                    ),
                  ),
                ),
                const Icon(
                  Icons.chevron_right_rounded,
                  color: Color(0xFF9CA3AF),
                  size: 18,
                ),
              ],
            ),
          ),
        )
      else
        // Period occurrence: date-range lasting N days
        _NumberStepper(
          value: _repeatPeriodDays,
          min: 1,
          max: 30,
          suffix: 'dia(s) de duração',
          onChanged: (v) => setState(() => _repeatPeriodDays = v),
        ),
      const SizedBox(height: 12),
      const Text(
        'O celular gera e alarma cada ocorrência mesmo sem conexão. Quando o PC '
        'estiver disponível, ele recebe uma cópia para acompanhar.',
        style: TextStyle(color: Color(0xFF5E6A7E), fontSize: 12),
      ),
      const SizedBox(height: 32),
    ];
  }

  Future<void> _save() async {
    final title = _titleController.text.trim();
    final notes = _notesController.text.trim();

    if (title.isEmpty || _saving) {
      if (title.isEmpty) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(
            content: Text('Informe um título'),
            backgroundColor: Color(0xFFEF4444),
          ),
        );
      }
      return;
    }

    if (_repeat) {
      final saved = await _saveRecurring(title, notes);
      if (saved && mounted) Navigator.pop(context, true);
      return;
    }

    if (_isDateRangeMode) {
      if (_startDate == null || _endDate == null) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(
            content: Text('Selecione data de início e fim'),
            backgroundColor: Color(0xFFEF4444),
          ),
        );
        return;
      }
    } else {
      if (_dueAt == null) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(
            content: Text('Selecione data e hora'),
            backgroundColor: Color(0xFFEF4444),
          ),
        );
        return;
      }
    }

    setState(() => _saving = true);

    try {
      if (_isDateRangeMode) {
        await TaskAlarmService.createQuickTask(
          title,
          dueAt: null,
          startDate: _startDate,
          endDate: _endDate,
          isDateRange: true,
          notes: notes,
        );
        if (!mounted) return;
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text(
              'Tarefa criada para ${_formatDate(_startDate!)} até ${_formatDate(_endDate!)}',
            ),
            backgroundColor: const Color(0xFF22C55E),
            behavior: SnackBarBehavior.floating,
          ),
        );
      } else {
        await TaskAlarmService.createQuickTask(
          title,
          dueAt: _dueAt,
          isDateRange: false,
          notes: notes,
          siriusCallEnabled: _siriusCallEnabled,
        );
        if (!mounted) return;
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text('Tarefa agendada para $_formatDateTime(_dueAt!)'),
            backgroundColor: const Color(0xFF22C55E),
            behavior: SnackBarBehavior.floating,
          ),
        );
      }

      if (!mounted) return;
      Navigator.pop(context, true); // Return true to indicate success
    } catch (e, stack) {
      print('[CreateTaskScreen] Error saving task: $e');
      print(stack);
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text('Erro ao criar tarefa: $e'),
          backgroundColor: const Color(0xFFEF4444),
          behavior: SnackBarBehavior.floating,
        ),
      );
    } finally {
      if (mounted) setState(() => _saving = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: const Color(0xFF07090F),
      appBar: AppBar(
        title: Text(
          _repeat
              ? 'Nova Tarefa Recorrente'
              : _isDateRangeMode
              ? 'Nova Tarefa (Período)'
              : 'Nova Tarefa (Horário)',
        ),
        backgroundColor: const Color(0xFF07090F),
        leading: IconButton(
          icon: const Icon(Icons.close_rounded),
          onPressed: () => Navigator.pop(context),
        ),
        actions: [
          TextButton.icon(
            onPressed: _saving
                ? null
                : () => setState(() => _isDateRangeMode = !_isDateRangeMode),
            icon: Icon(
              _isDateRangeMode ? Icons.schedule : Icons.date_range,
              size: 20,
            ),
            label: Text(_isDateRangeMode ? 'Horário' : 'Período'),
            style: TextButton.styleFrom(
              foregroundColor: const Color(0xFF6366F1),
            ),
          ),
        ],
      ),
      body: SingleChildScrollView(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            // Title field
            TextField(
              controller: _titleController,
              textCapitalization: TextCapitalization.sentences,
              maxLength: 200,
              style: const TextStyle(color: Colors.white),
              decoration: InputDecoration(
                counterText: '',
                hintText: 'Ex.: Estudar Flutter',
                hintStyle: TextStyle(
                  color: const Color(0xFFFFFFFF).withOpacity(0.3),
                ),
                prefixIcon: const Icon(
                  Icons.edit_note_rounded,
                  color: Color(0xFF6366F1),
                ),
                labelText: 'Título *',
                labelStyle: const TextStyle(color: Color(0xFF9CA3AF)),
              ),
            ),
            if (!_isDateRangeMode && !_repeat) ...[
              const SizedBox(height: 12),
              Wrap(
                spacing: 8,
                children: [
                  for (final offset in [0, 1])
                    ActionChip(
                      label: Text(offset == 0 ? 'Hoje' : 'Amanhã'),
                      onPressed: () {
                        final now = DateTime.now();
                        final selected = DateTime(
                          now.year,
                          now.month,
                          now.day + offset,
                        );
                        final base =
                            _dueAt ?? now.add(const Duration(hours: 1));
                        final candidate = DateTime(
                          selected.year,
                          selected.month,
                          selected.day,
                          base.hour,
                          base.minute,
                        );
                        final nextHour = now.add(const Duration(hours: 1));
                        setState(
                          () => _dueAt = candidate.isBefore(now)
                              ? (nextHour.day == now.day
                                    ? nextHour
                                    : DateTime(
                                        now.year,
                                        now.month,
                                        now.day,
                                        23,
                                        59,
                                      ))
                              : candidate,
                        );
                      },
                    ),
                ],
              ),
            ],
            const SizedBox(height: 24),

            // Mode indicator
            Container(
              padding: const EdgeInsets.all(12),
              decoration: BoxDecoration(
                color: _isDateRangeMode
                    ? const Color(0xFFF59E0B).withValues(alpha: 0.1)
                    : const Color(0xFF6366F1).withValues(alpha: 0.1),
                borderRadius: BorderRadius.circular(12),
                border: Border.all(
                  color: _isDateRangeMode
                      ? const Color(0xFFF59E0B).withValues(alpha: 0.4)
                      : const Color(0xFF6366F1).withValues(alpha: 0.4),
                ),
              ),
              child: Row(
                children: [
                  Icon(
                    _isDateRangeMode ? Icons.date_range : Icons.schedule,
                    color: _isDateRangeMode
                        ? const Color(0xFFF59E0B)
                        : const Color(0xFF6366F1),
                  ),
                  const SizedBox(width: 10),
                  Expanded(
                    child: Text(
                      _repeat
                          ? 'Repete automaticamente — ${_repeatSummary()}'
                          : _isDateRangeMode
                          ? 'Modo Período: a tarefa aparecerá como notificação diária às 00:00 de ${_formatDate(_startDate ?? DateTime.now())} até ${_formatDate(_endDate ?? DateTime.now().add(const Duration(days: 1)))}'
                          : 'Modo Horário: alarme único no horário exato definido',
                      style: TextStyle(
                        color: _isDateRangeMode
                            ? const Color(0xFFF59E0B)
                            : const Color(0xFF6366F1),
                        fontSize: 13,
                        fontWeight: FontWeight.w500,
                      ),
                    ),
                  ),
                ],
              ),
            ),
            const SizedBox(height: 24),

            ExpansionTile(
              title: const Text('Repetição e lembretes'),
              subtitle: const Text('Configure quando e como o Sirius avisa'),
              children: [
                // "Repetir" toggle — reveals the recurrence options below
                Container(
                  decoration: BoxDecoration(
                    color: const Color(
                      0xFFFFFFFF,
                    ).withValues(alpha: _repeat ? 0.08 : 0.03),
                    borderRadius: BorderRadius.circular(12),
                    border: Border.all(
                      color: _repeat
                          ? const Color(0xFF22C55E).withValues(alpha: 0.5)
                          : const Color(0xFFFFFFFF).withValues(alpha: 0.1),
                    ),
                  ),
                  child: SwitchListTile(
                    value: _repeat,
                    onChanged: (v) => setState(() => _repeat = v),
                    activeThumbColor: const Color(0xFF22C55E),
                    contentPadding: const EdgeInsets.symmetric(horizontal: 12),
                    title: const Row(
                      children: [
                        Icon(
                          Icons.repeat_rounded,
                          color: Color(0xFF22C55E),
                          size: 20,
                        ),
                        SizedBox(width: 10),
                        Text(
                          'Repetir automaticamente',
                          style: TextStyle(
                            color: Colors.white,
                            fontWeight: FontWeight.w600,
                          ),
                        ),
                      ],
                    ),
                    subtitle: Text(
                      'A tarefa é recriada sozinha a cada ocorrência',
                      style: TextStyle(
                        color: const Color(0xFFFFFFFF).withOpacity(0.4),
                        fontSize: 12,
                      ),
                    ),
                  ),
                ),

                // Recurrence options (only when the toggle is ON)
                if (_repeat) ..._buildRecurrenceOptions(),

                if (!_repeat) const SizedBox(height: 24),

                if (!_isDateRangeMode) ...[
                  SwitchListTile(
                    value: _siriusCallEnabled,
                    onChanged: (value) =>
                        setState(() => _siriusCallEnabled = value),
                    activeThumbColor: const Color(0xFF22C55E),
                    title: const Text(
                      'Ligação simulada do Sirius',
                      style: TextStyle(color: Colors.white),
                    ),
                    subtitle: Text(
                      _callCapabilityHint,
                      style: TextStyle(
                        color: Colors.white.withValues(alpha: 0.55),
                        fontSize: 12,
                      ),
                    ),
                    secondary: const Icon(
                      Icons.call_rounded,
                      color: Color(0xFF22C55E),
                    ),
                  ),
                  if (!_dndAccessGranted)
                    Align(
                      alignment: Alignment.centerLeft,
                      child: TextButton.icon(
                        onPressed:
                            TaskAlarmService.openDoNotDisturbAccessSettings,
                        icon: const Icon(Icons.do_not_disturb_on_rounded),
                        label: const Text('Configurar acesso ao Não Perturbe'),
                      ),
                    ),
                  const SizedBox(height: 12),
                ],
              ],
            ),
            const SizedBox(height: 20),
            // Date pickers
            if (!_repeat && _isDateRangeMode) ...[
              const Text(
                'PERÍODO (obrigatório)',
                style: TextStyle(
                  color: Color(0xFFF59E0B),
                  fontSize: 12,
                  fontWeight: FontWeight.w700,
                  letterSpacing: 1,
                ),
              ),
              const SizedBox(height: 12),
              Row(
                children: [
                  Expanded(
                    child: _DatePickerChip(
                      label: 'Início',
                      value: _startDate,
                      formatter: _formatDate,
                      color: const Color(0xFFF59E0B),
                      onTap: _pickStartDate,
                    ),
                  ),
                  const SizedBox(width: 12),
                  Expanded(
                    child: _DatePickerChip(
                      label: 'Fim',
                      value: _endDate,
                      formatter: _formatDate,
                      color: const Color(0xFFF59E0B),
                      enabled: _startDate != null,
                      onTap: _pickEndDate,
                    ),
                  ),
                ],
              ),
            ] else if (!_repeat) ...[
              const Text(
                'DATA E HORA (obrigatório)',
                style: TextStyle(
                  color: Color(0xFF6366F1),
                  fontSize: 12,
                  fontWeight: FontWeight.w700,
                  letterSpacing: 1,
                ),
              ),
              const SizedBox(height: 12),
              Row(
                children: [
                  Expanded(
                    child: _DatePickerChip(
                      label: 'Data',
                      value: _dueAt,
                      formatter: _formatDate,
                      color: const Color(0xFF6366F1),
                      onTap: _pickDueDate,
                    ),
                  ),
                  const SizedBox(width: 12),
                  Expanded(
                    child: _DatePickerChip(
                      label: 'Hora',
                      value: _dueAt,
                      formatter: (d) =>
                          '${d.hour.toString().padLeft(2, '0')}:${d.minute.toString().padLeft(2, '0')}',
                      color: const Color(0xFF6366F1),
                      onTap: _pickDueTime,
                    ),
                  ),
                ],
              ),
            ],
            const SizedBox(height: 24),

            // Optional time for date-range mode
            if (!_repeat && _isDateRangeMode) ...[
              const Text(
                'HORÁRIO OPCIONAL',
                style: TextStyle(
                  color: Color(0xFF9CA3AF),
                  fontSize: 12,
                  fontWeight: FontWeight.w700,
                  letterSpacing: 1,
                ),
              ),
              const SizedBox(height: 8),
              Text(
                'Se definido, o horário fica na tarefa. A notificação de 00:00 mostra "Nome - (01/01 a 01/01)" com a descrição da tarefa.',
                style: TextStyle(color: const Color(0xFF5E6A7E), fontSize: 12),
              ),
              const SizedBox(height: 12),
              Row(
                children: [
                  Expanded(
                    child: _DatePickerChip(
                      label: 'Horário (opcional)',
                      value: _dueAt,
                      formatter: (d) =>
                          '${d.hour.toString().padLeft(2, '0')}:${d.minute.toString().padLeft(2, '0')}',
                      color: const Color(0xFF9CA3AF),
                      onTap: _pickDueTime,
                    ),
                  ),
                  if (_dueAt != null) ...[
                    const SizedBox(width: 12),
                    IconButton(
                      icon: const Icon(Icons.clear, color: Color(0xFF9CA3AF)),
                      onPressed: () => setState(() => _dueAt = null),
                    ),
                  ],
                ],
              ),
              const SizedBox(height: 24),
            ],

            // Notes field
            const Text(
              'OBSERVAÇÕES (opcional)',
              style: TextStyle(
                color: Color(0xFF9CA3AF),
                fontSize: 12,
                fontWeight: FontWeight.w700,
                letterSpacing: 1,
              ),
            ),
            const SizedBox(height: 8),
            TextField(
              controller: _notesController,
              textCapitalization: TextCapitalization.sentences,
              maxLines: 3,
              style: const TextStyle(color: Colors.white),
              decoration: const InputDecoration(
                hintText: 'Detalhes adicionais...',
                hintStyle: TextStyle(color: Color(0xFF5E6A7E)),
                prefixIcon: Padding(
                  padding: EdgeInsets.only(bottom: 48),
                  child: Icon(Icons.notes, color: Color(0xFF6366F1)),
                ),
              ),
            ),
            const SizedBox(height: 32),

            // Save button
            SizedBox(
              width: double.infinity,
              child: FilledButton.icon(
                onPressed: _saving ? null : _save,
                icon: _saving
                    ? const SizedBox(
                        width: 20,
                        height: 20,
                        child: CircularProgressIndicator(
                          strokeWidth: 2,
                          color: Colors.white,
                        ),
                      )
                    : const Icon(Icons.save_outlined),
                label: Text(
                  _isDateRangeMode
                      ? 'Criar Tarefa de Período'
                      : 'Agendar Tarefa',
                ),
                style: FilledButton.styleFrom(
                  padding: const EdgeInsets.symmetric(vertical: 16),
                  backgroundColor: _isDateRangeMode
                      ? const Color(0xFFF59E0B)
                      : const Color(0xFF6366F1),
                  shape: RoundedRectangleBorder(
                    borderRadius: BorderRadius.circular(14),
                  ),
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

/// Selectable pill used by the recurrence options (type, Horário/Período).
class _OptionChip extends StatelessWidget {
  final String label;
  final IconData icon;
  final bool selected;
  final Color color;
  final VoidCallback onTap;

  const _OptionChip({
    required this.label,
    required this.icon,
    required this.selected,
    required this.color,
    required this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    return InkWell(
      onTap: onTap,
      borderRadius: BorderRadius.circular(12),
      child: Container(
        padding: const EdgeInsets.symmetric(vertical: 9, horizontal: 14),
        decoration: BoxDecoration(
          color: selected
              ? color.withValues(alpha: 0.15)
              : const Color(0xFFFFFFFF).withValues(alpha: 0.04),
          borderRadius: BorderRadius.circular(12),
          border: Border.all(
            color: selected
                ? color
                : const Color(0xFFFFFFFF).withValues(alpha: 0.1),
            width: selected ? 2 : 1,
          ),
        ),
        child: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(
              icon,
              size: 16,
              color: selected ? color : const Color(0xFF9CA3AF),
            ),
            const SizedBox(width: 6),
            Text(
              label,
              style: TextStyle(
                fontSize: 13,
                fontWeight: selected ? FontWeight.w700 : FontWeight.w500,
                color: selected ? color : const Color(0xFF9CA3AF),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

/// Selectable single weekday (S T Q Q S S D row).
class _WeekdayChip extends StatelessWidget {
  final String label;
  final bool selected;
  final VoidCallback onTap;

  const _WeekdayChip({
    required this.label,
    required this.selected,
    required this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    return InkWell(
      onTap: onTap,
      borderRadius: BorderRadius.circular(10),
      child: Container(
        height: 42,
        decoration: BoxDecoration(
          color: selected
              ? const Color(0xFF22C55E).withValues(alpha: 0.2)
              : const Color(0xFFFFFFFF).withValues(alpha: 0.04),
          borderRadius: BorderRadius.circular(10),
          border: Border.all(
            color: selected
                ? const Color(0xFF22C55E)
                : const Color(0xFFFFFFFF).withValues(alpha: 0.1),
            width: selected ? 2 : 1,
          ),
        ),
        alignment: Alignment.center,
        child: Text(
          label,
          style: TextStyle(
            fontSize: 12,
            fontWeight: selected ? FontWeight.w700 : FontWeight.w500,
            color: selected ? const Color(0xFF22C55E) : const Color(0xFF9CA3AF),
          ),
        ),
      ),
    );
  }
}

/// -/+ numeric selector used for interval days, month day and period length.
class _NumberStepper extends StatelessWidget {
  final int value;
  final int min;
  final int max;
  final String suffix;
  final ValueChanged<int> onChanged;

  const _NumberStepper({
    required this.value,
    required this.min,
    required this.max,
    required this.suffix,
    required this.onChanged,
  });

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 6),
      decoration: BoxDecoration(
        color: const Color(0xFFFFFFFF).withValues(alpha: 0.04),
        borderRadius: BorderRadius.circular(12),
        border: Border.all(
          color: const Color(0xFFFFFFFF).withValues(alpha: 0.1),
        ),
      ),
      child: Row(
        children: [
          IconButton(
            onPressed: value > min ? () => onChanged(value - 1) : null,
            icon: const Icon(Icons.remove_circle_outline_rounded),
            color: const Color(0xFFEF4444),
            iconSize: 24,
          ),
          Expanded(
            child: Text.rich(
              TextSpan(
                children: [
                  TextSpan(
                    text: '$value',
                    style: const TextStyle(
                      color: Colors.white,
                      fontSize: 18,
                      fontWeight: FontWeight.w700,
                    ),
                  ),
                  TextSpan(
                    text: '  $suffix',
                    style: const TextStyle(
                      color: Color(0xFF9CA3AF),
                      fontSize: 12,
                    ),
                  ),
                ],
              ),
              textAlign: TextAlign.center,
            ),
          ),
          IconButton(
            onPressed: value < max ? () => onChanged(value + 1) : null,
            icon: const Icon(Icons.add_circle_outline_rounded),
            color: const Color(0xFF22C55E),
            iconSize: 24,
          ),
        ],
      ),
    );
  }
}

class _DatePickerChip extends StatelessWidget {
  final String label;
  final DateTime? value;
  final String Function(DateTime) formatter;
  final Color color;
  final bool enabled;
  final VoidCallback onTap;

  const _DatePickerChip({
    required this.label,
    required this.value,
    required this.formatter,
    required this.color,
    this.enabled = true,
    required this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    return InkWell(
      onTap: enabled ? onTap : null,
      borderRadius: BorderRadius.circular(12),
      child: Container(
        padding: const EdgeInsets.symmetric(vertical: 14, horizontal: 16),
        decoration: BoxDecoration(
          color: const Color(
            0xFFFFFFFF,
          ).withValues(alpha: enabled ? 0.06 : 0.03),
          borderRadius: BorderRadius.circular(12),
          border: Border.all(
            color: value != null
                ? color
                : const Color(0xFFFFFFFF).withValues(alpha: 0.1),
            width: value != null ? 2 : 1,
          ),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              label,
              style: TextStyle(
                fontSize: 10,
                color: value != null ? color : const Color(0xFF5E6A7E),
                fontWeight: FontWeight.w700,
                letterSpacing: 0.5,
              ),
            ),
            const SizedBox(height: 4),
            Row(
              children: [
                Icon(
                  value != null
                      ? Icons.calendar_today_rounded
                      : Icons.add_rounded,
                  size: 16,
                  color: value != null ? color : const Color(0xFF5E6A7E),
                ),
                const SizedBox(width: 8),
                Text(
                  value != null ? formatter(value!) : 'Selecionar',
                  style: TextStyle(
                    fontSize: 14,
                    color: value != null
                        ? Colors.white
                        : const Color(0xFF9CA3AF),
                    fontWeight: value != null
                        ? FontWeight.w600
                        : FontWeight.w400,
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
