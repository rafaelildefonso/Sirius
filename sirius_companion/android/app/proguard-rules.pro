# MediaPipe Tasks GenAI 0.10.27 references these protobuf-generated
# annotations/types. They are optional to the runtime, but R8 must not
# treat their absence as a fatal missing-class error.
-dontwarn com.google.protobuf.Internal$ProtoMethodMayReturnNull
-dontwarn com.google.protobuf.Internal$ProtoNonnullApi
-dontwarn com.google.protobuf.ProtoField
-dontwarn com.google.protobuf.ProtoPresenceBits
-dontwarn com.google.protobuf.ProtoPresenceCheckedField

# Notification receivers and helpers are reached by Android broadcasts and
# persisted scheduled intents, so R8 cannot reliably discover every usage.
-keep class com.dexterous.flutterlocalnotifications.** { *; }
