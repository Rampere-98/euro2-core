import 'dart:js_interop';

import 'package:flutter/foundation.dart';

@JS('euro2Install')
external JSPromise<JSString> _euro2Install();

@JS('euro2IsStandalone')
external JSBoolean _euro2IsStandalone();

@JS('euro2InstallPrompt')
external JSAny? _euro2InstallPrompt;

/// Browser install (PWA) helpers; no-ops outside the web build.
class Install {
  static bool get isWeb => kIsWeb;

  static bool get alreadyInstalled {
    if (!kIsWeb) return true;
    try {
      return _euro2IsStandalone().toDart;
    } catch (_) {
      return false;
    }
  }

  /// True when Chrome/Edge (Android, desktop) captured the native install prompt.
  static bool get canPromptNatively {
    if (!kIsWeb) return false;
    try {
      return _euro2InstallPrompt != null;
    } catch (_) {
      return false;
    }
  }

  static Future<String> prompt() async {
    if (!kIsWeb) return 'unavailable';
    try {
      return (await _euro2Install().toDart).toDart;
    } catch (_) {
      return 'unavailable';
    }
  }
}
