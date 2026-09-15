import 'package:flutter/material.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'api.dart';

/// Session state: API location, login token and the current user.
class AppState extends ChangeNotifier {
  AppState(this.api) : defaultBaseUrl = api.baseUrl;

  final Euro2Api api;
  Map<String, dynamic>? user;
  int unreadNotifications = 0;

  /// Type ids the user follows, loaded once per session so coin pages need not fetch the list.
  Set<String>? watchlistIds;

  /// Preferences have been read from disk (the shell waits for this before the tour).
  bool restored = false;
  bool onboardingDone = false;
  final String defaultBaseUrl;

  // Preferences (Ajustes), persisted locally on this device.
  String lang = 'es';
  ThemeMode themeMode = ThemeMode.system;
  bool sharePurchases = true;
  bool notifyDeals = true;
  bool notifyMoves = true;
  Set<String> marketplaces = {'EBAY_ES', 'EBAY_DE', 'EBAY_FR', 'EBAY_IT'};

  bool get loggedIn => user != null;
  bool get isPro => user?['plan'] == 'pro';
  bool get isAdmin => user?['role'] == 'admin';

  Future<void> restore() async {
    final prefs = await SharedPreferences.getInstance();
    api.baseUrl = prefs.getString('baseUrl') ?? api.baseUrl;
    lang = prefs.getString('lang') ?? 'es';
    api.lang = lang;
    themeMode = ThemeMode.values[prefs.getInt('themeMode') ?? ThemeMode.system.index];
    sharePurchases = prefs.getBool('sharePurchases') ?? true;
    notifyDeals = prefs.getBool('notifyDeals') ?? true;
    notifyMoves = prefs.getBool('notifyMoves') ?? true;
    marketplaces = (prefs.getStringList('marketplaces') ?? marketplaces.toList()).toSet();
    onboardingDone = prefs.getBool('onboarding_done_v1') ?? false;
    api.token = prefs.getString('token');
    if (api.token != null) {
      try {
        user = Map<String, dynamic>.from(await api.get('/me'));
        await refreshNotifications();
      } catch (_) {
        api.token = null;
        await prefs.remove('token');
      }
    }
    restored = true;
    notifyListeners();
  }

  Future<void> setBaseUrl(String url) async {
    api.baseUrl = url.trim().isEmpty ? defaultBaseUrl : url.trim().replaceAll(RegExp(r'/+$'), '');
    (await SharedPreferences.getInstance()).setString('baseUrl', api.baseUrl);
    notifyListeners();
  }

  Future<void> setLang(String value) async {
    lang = value;
    api.lang = value;
    (await SharedPreferences.getInstance()).setString('lang', value);
    notifyListeners();
  }

  Future<void> setThemeMode(ThemeMode mode) async {
    themeMode = mode;
    (await SharedPreferences.getInstance()).setInt('themeMode', mode.index);
    notifyListeners();
  }

  Future<void> setFlag(String key, bool value) async {
    switch (key) {
      case 'sharePurchases':
        sharePurchases = value;
      case 'notifyDeals':
        notifyDeals = value;
      case 'notifyMoves':
        notifyMoves = value;
    }
    (await SharedPreferences.getInstance()).setBool(key, value);
    notifyListeners();
  }

  Future<void> setMarketplaces(Set<String> codes) async {
    marketplaces = codes;
    (await SharedPreferences.getInstance()).setStringList('marketplaces', codes.toList());
    notifyListeners();
  }

  Future<void> markOnboardingDone() async {
    onboardingDone = true;
    (await SharedPreferences.getInstance()).setBool('onboarding_done_v1', true);
    notifyListeners();
  }

  Future<void> clearLocalData() async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.clear();
    // the tour is not "data": nobody wants it again after clearing a cache
    if (onboardingDone) await prefs.setBool('onboarding_done_v1', true);
    api.token = null;
    user = null;
    api.baseUrl = defaultBaseUrl;
    notifyListeners();
  }

  Future<void> _applyToken(Map<String, dynamic> body) async {
    api.token = body['access_token'] as String;
    user = Map<String, dynamic>.from(body['user']);
    (await SharedPreferences.getInstance()).setString('token', api.token!);
    await refreshNotifications();
    notifyListeners();
  }

  Future<void> register(String email, String password, String name, String? country) async {
    final body = await api.post(
      '/auth/register',
      body: {
        'email': email,
        'password': password,
        'display_name': name,
        if (country != null && country.isNotEmpty) 'country_code': country,
      },
    );
    await _applyToken(Map<String, dynamic>.from(body));
  }

  Future<void> login(String email, String password) async {
    final body = await api.post('/auth/login', body: {'email': email, 'password': password});
    await _applyToken(Map<String, dynamic>.from(body));
  }

  Future<void> logout() async {
    api.token = null;
    user = null;
    watchlistIds = null;
    (await SharedPreferences.getInstance()).remove('token');
    notifyListeners();
  }

  Future<void> upgradeToPro() async {
    user = Map<String, dynamic>.from(await api.post('/me/plan/pro'));
    notifyListeners();
  }

  Future<void> refreshNotifications() async {
    if (!loggedIn) return;
    final list = List<Map<String, dynamic>>.from(await api.get('/me/notifications'));
    unreadNotifications = list.where((n) => n['read_at'] == null).length;
    notifyListeners();
  }

  Future<bool> isWatching(String typeId) async {
    if (!loggedIn) return false;
    if (watchlistIds == null) {
      final list = List<Map<String, dynamic>>.from(await api.get('/me/watchlist'));
      watchlistIds = {for (final w in list) w['type']['id'] as String};
    }
    return watchlistIds!.contains(typeId);
  }

  Future<void> setWatching(String typeId, bool watching) async {
    if (watching) {
      await api.post('/me/watchlist', body: {'type_id': typeId});
      watchlistIds?.add(typeId);
    } else {
      await api.delete('/me/watchlist/$typeId');
      watchlistIds?.remove(typeId);
    }
  }
}
