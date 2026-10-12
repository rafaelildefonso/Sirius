import 'package:flutter/material.dart';
import '../../../core/storage/database/database.dart';
import '../task_alarm_service.dart';

/// Full-screen task editor. The task mode (date-range vs time-specific) is
/// locked to the existing task — only title, notes and that mode's dates can
/// change. Returns `true` via [Navigator.pop] when the edit was saved.
class EditTaskScreen extends StatefulWidget {
  final ScheduledTask task;

  const EditTaskScreen({super.key, required this.task});

  @override
  State<EditTaskScreen> createState() => _EditTaskScreenState();
}

class _EditTaskScreenState extends State<EditTaskScreen> {
  late final TextEditingController _titleController;
  late final TextEditingController _notesController;

  // Date-range mode
  DateTime? _startDate;
  DateTime? _endDate;

  // Time-specific mode
  DateTime? _dueAt;

  late final bool _isDateRangeMode;
  bool _saving = false;

  @override
  void initState() {
    super.initState();
    final task = widget.task;
    _titleController = TextEditingController(text: task.title);
    _notesController = TextEditingController(text: task.notes ?? '');
    _isDateRangeMode = task.isDateRange;
    _startDate = task.startDate;
    _endDate = task.endDate;
    _dueAt = task.dueAt;
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
      firstDate: now.subtract(const Duration(days: 365)),
      lastDate: now.add(const Duration(days: 365 * 2)),
    );
    if (date == null) return;
    setState(() {
      _startDate = DateTime(date.year, date.month, date.day);
      // Ensure end date is not before start date
      if (_endDate != null && _endDate!.isBefore(_startDate!)) {
        _endDate = _startDate;
      }
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
      firstDate: now.subtract(const Duration(days: 365)),
      lastDate: now.add(const Duration(days: 365 * 2)),
    );
    if (date == null) return;
    setState(() {
      _dueAt = DateTime(date.year, date.month, date.day,
          _dueAt?.hour ?? 9, _dueAt?.minute ?? 0);
    });
  }

  Future<void> _pickDueTime() async {
    final base = _dueAt ?? DateTime.now().add(const Duration(hours: 1));
    final time = await showTimePicker(
      context: context,
      initialTime: TimeOfDay.fromDateTime(base),
    );
    if (time == null) return;
    final picked =
        DateTime(base.year, base.month, base.day, time.hour, time.minute);
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

  Future<void> _save() async {
    final title = _titleController.text.trim();
    final notes = _notesController.text.trim();

    if (title.isEmpty || _saving) return;

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
      final ok = await TaskAlarmService.editTask(
        widget.task.remoteId,
        title: title,
        notes: notes,
        dueAt: _dueAt,
        startDate: _startDate,
        endDate: _endDate,
      );
      if (!mounted) return;
      if (!ok) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(
            content: Text('Não foi possível editar a tarefa'),
            backgroundColor: Color(0xFFEF4444),
          ),
        );
        return;
      }
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text(
            _isDateRangeMode
                ? 'Tarefa editada: ${_formatDate(_startDate!)} até ${_formatDate(_endDate!)}'
                : 'Tarefa editada para $_formatDateTime(_dueAt!)',
          ),
          backgroundColor: const Color(0xFF22C55E),
          behavior: SnackBarBehavior.floating,
        ),
      );
      Navigator.pop(context, true); // Return true to indicate success
    } catch (e, stack) {
      print('[EditTaskScreen] Error saving task: $e');
      print(stack);
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text('Erro ao editar tarefa: $e'),
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
        title: Text(_isDateRangeMode ? 'Editar Tarefa (Período)' : 'Editar Tarefa (Horário)'),
        backgroundColor: const Color(0xFF07090F),
        leading: IconButton(
          icon: const Icon(Icons.close_rounded),
          onPressed: () => Navigator.pop(context),
        ),
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
                hintStyle: TextStyle(color: const Color(0xFFFFFFFF).withOpacity(0.3)),
                prefixIcon: const Icon(Icons.edit_note_rounded, color: Color(0xFF6366F1)),
                labelText: 'Título *',
                labelStyle: const TextStyle(color: Color(0xFF9CA3AF)),
              ),
            ),
            const SizedBox(height: 24),

            // Mode indicator (fixed for existing tasks)
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
                    color: _isDateRangeMode ? const Color(0xFFF59E0B) : const Color(0xFF6366F1),
                  ),
                  const SizedBox(width: 10),
                  Expanded(
                    child: Text(
                      _isDateRangeMode
                          ? 'Modo Período: notificação diária às 00:00 dentro do período'
                          : 'Modo Horário: alarme único no horário exato definido',
                      style: TextStyle(
                        color: _isDateRangeMode ? const Color(0xFFF59E0B) : const Color(0xFF6366F1),
                        fontSize: 13,
                        fontWeight: FontWeight.w500,
                      ),
                    ),
                  ),
                ],
              ),
            ),
            const SizedBox(height: 24),

            // Date pickers
            if (_isDateRangeMode) ...[
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
            ] else ...[
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
                        child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white),
                      )
                    : const Icon(Icons.save_outlined),
                label: const Text('Salvar Alterações'),
                style: FilledButton.styleFrom(
                  padding: const EdgeInsets.symmetric(vertical: 16),
                  backgroundColor: _isDateRangeMode ? const Color(0xFFF59E0B) : const Color(0xFF6366F1),
                  shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(14)),
                ),
              ),
            ),
          ],
        ),
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
          color: const Color(0xFFFFFFFF).withValues(alpha: enabled ? 0.06 : 0.03),
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
                  value != null ? Icons.calendar_today_rounded : Icons.add_rounded,
                  size: 16,
                  color: value != null ? color : const Color(0xFF5E6A7E),
                ),
                const SizedBox(width: 8),
                Text(
                  value != null ? formatter(value!) : 'Selecionar',
                  style: TextStyle(
                    fontSize: 14,
                    color: value != null ? Colors.white : const Color(0xFF9CA3AF),
                    fontWeight: value != null ? FontWeight.w600 : FontWeight.w400,
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
