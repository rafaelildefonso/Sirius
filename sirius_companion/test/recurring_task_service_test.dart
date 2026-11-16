import 'package:flutter_test/flutter_test.dart';
import 'package:sirius_companion/features/tasks/recurring_task_service.dart';

void main() {
  group('RecurringTaskService.nextOccurrence', () {
    test('finds the next selected weekday', () {
      final next = RecurringTaskService.nextOccurrence({
        'recurrence_type': 'weekly',
        'weekdays': [0, 2],
        'start_from': '2026-11-01',
      }, DateTime(2026, 11, 3));

      expect(next, DateTime(2026, 11, 4));
    });

    test('keeps interval days anchored to start_from', () {
      final next = RecurringTaskService.nextOccurrence({
        'recurrence_type': 'interval',
        'interval_days': 3,
        'start_from': '2026-11-01',
      }, DateTime(2026, 11, 3));

      expect(next, DateTime(2026, 11, 4));
    });

    test('clamps monthly day to the last day of the month', () {
      final next = RecurringTaskService.nextOccurrence({
        'recurrence_type': 'monthly',
        'month_day': 31,
        'start_from': '2026-11-01',
      }, DateTime(2027, 2, 1));

      expect(next, DateTime(2027, 2, 28));
    });

    test('returns null after the recurrence end date', () {
      final next = RecurringTaskService.nextOccurrence({
        'recurrence_type': 'daily',
        'start_from': '2026-11-01',
        'end_date': '2026-11-02',
      }, DateTime(2026, 11, 3));

      expect(next, isNull);
    });
  });
}
