import 'package:drift/drift.dart';

@DataClassName('SyncItem')
class SyncItems extends Table {
  IntColumn get id => integer().autoIncrement()();
  TextColumn get type => text().withLength(min: 1, max: 50)();
  TextColumn get payloadJson => text()();
  DateTimeColumn get createdAt => dateTime()();
  DateTimeColumn get syncedAt => dateTime().nullable()();
  IntColumn get retryCount => integer().withDefault(const Constant(0))();
  TextColumn get lastError => text().nullable()();
  TextColumn get clientId => text().unique()();
}

@DataClassName('Place')
class Places extends Table {
  IntColumn get id => integer().autoIncrement()();
  TextColumn get uuid => text().unique()();
  TextColumn get name => text()();
  RealColumn get latitude => real()();
  RealColumn get longitude => real()();
  RealColumn get radiusMeters => real().withDefault(const Constant(100.0))();
  BoolColumn get isActive => boolean().withDefault(const Constant(true))();
  DateTimeColumn get createdAt => dateTime()();
  DateTimeColumn get lastTriggeredAt => dateTime().nullable()();
  IntColumn get triggerCount => integer().withDefault(const Constant(0))();
}

@DataClassName('ScheduledTask')
class ScheduledTasks extends Table {
  TextColumn get remoteId => text().unique()();
  TextColumn get title => text()();
  TextColumn get notes => text().nullable()();
  DateTimeColumn get dueAt => dateTime().nullable()();
  TextColumn get status => text().withDefault(const Constant('pending'))();
  TextColumn get source => text().withDefault(const Constant('phone'))();
  BoolColumn get alarmScheduled =>
      boolean().withDefault(const Constant(false))();
  DateTimeColumn get createdAt => dateTime()();
  DateTimeColumn get updatedAt => dateTime()();
  DateTimeColumn get startDate => dateTime().nullable()();
  DateTimeColumn get endDate => dateTime().nullable()();
  BoolColumn get isDateRange => boolean().withDefault(const Constant(false))();
}

@DataClassName('Note')
class Notes extends Table {
  IntColumn get id => integer().autoIncrement()();
  TextColumn get uuid => text().unique()();
  TextColumn get title => text().withDefault(const Constant(''))();
  TextColumn get content => text()();
  TextColumn get category => text()();
  TextColumn get aiSummary => text().nullable()();
  TextColumn get aiTags => text().nullable()();
  TextColumn get classificationStatus =>
      text().withDefault(const Constant('pending'))();
  TextColumn get classificationError => text().nullable()();
  TextColumn get attachmentPaths => text().nullable()();
  IntColumn get totalAttachmentBytes =>
      integer().withDefault(const Constant(0))();
  TextColumn get syncStatus => text().withDefault(const Constant('pending'))();
  DateTimeColumn get syncedAt => dateTime().nullable()();
  DateTimeColumn get createdAt => dateTime()();
  DateTimeColumn get updatedAt => dateTime()();
}

@DataClassName('PlaceVisit')
class PlaceVisits extends Table {
  IntColumn get id => integer().autoIncrement()();
  TextColumn get uuid => text().unique()();
  TextColumn get placeId => text()();
  TextColumn get placeName => text()();
  DateTimeColumn get enteredAt => dateTime()();
  DateTimeColumn get exitedAt => dateTime().nullable()();
  IntColumn get durationSeconds => integer().withDefault(const Constant(0))();
  BoolColumn get confirmed => boolean().withDefault(const Constant(false))();
  TextColumn get syncStatus => text().withDefault(const Constant('pending'))();
  DateTimeColumn get createdAt => dateTime()();
}
