import 'dart:js_interop';

import 'package:flutter/foundation.dart';

@JS('euro2Device')
external JSString _euro2Device();

@JS('euro2IsStandalone')
external JSBoolean _euro2IsStandalone();

enum DeviceKind { ios, android, desktop }

/// What the app is running on, so copy, gestures and install help can match the device.
/// On the web the kind comes from the user agent (see index.html); elsewhere from the platform.
class Device {
  static DeviceKind? _kind;
  static bool? _pwa;

  static DeviceKind get kind => _kind ??= _detect();
  static bool get isIos => kind == DeviceKind.ios;
  static bool get isAndroid => kind == DeviceKind.android;
  static bool get isDesktop => kind == DeviceKind.desktop;
  static bool get isTouch => !isDesktop;

  /// Installed to the home screen (standalone display mode) rather than open in a browser tab.
  static bool get isPwa => _pwa ??= _standalone();

  static String get label => switch (kind) {
    DeviceKind.ios => 'iPhone / iPad',
    DeviceKind.android => 'Android',
    DeviceKind.desktop => 'Ordenador',
  };

  static DeviceKind _detect() {
    if (kIsWeb) {
      try {
        return DeviceKind.values.byName(_euro2Device().toDart);
      } catch (_) {
        return DeviceKind.desktop;
      }
    }
    return switch (defaultTargetPlatform) {
      TargetPlatform.iOS => DeviceKind.ios,
      TargetPlatform.android => DeviceKind.android,
      _ => DeviceKind.desktop,
    };
  }

  static bool _standalone() {
    if (!kIsWeb) return true;
    try {
      return _euro2IsStandalone().toDart;
    } catch (_) {
      return false;
    }
  }
}
