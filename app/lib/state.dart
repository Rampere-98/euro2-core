import 'package:flutter/foundation.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'api.dart';

/// Session state: API location, login token and the current user.
class AppState extends ChangeNotifier {
  AppState(this.api);

  final Euro2Api api;
  Map<String, dynamic>? user;
  int unreadNotifications = 0;

  bool get loggedIn => user != null;
  bool get isPro => user?['plan'] == 'pro';

  Future<void> restore() async {
    final prefs = await SharedPreferences.getInstance();
    api.baseUrl = prefs.getString('baseUrl') ?? api.baseUrl;
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
    notifyListeners();
  }

  Future<void> setBaseUrl(String url) async {
    api.baseUrl = url.trim().replaceAll(RegExp(r'/+$'), '');
    (await SharedPreferences.getInstance()).setString('baseUrl', api.baseUrl);
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
    final body = await api.post('/auth/register', body: {
      'email': email,
      'password': password,
      'display_name': name,
      if (country != null && country.isNotEmpty) 'country_code': country,
    });
    await _applyToken(Map<String, dynamic>.from(body));
  }

  Future<void> login(String email, String password) async {
    final body = await api.post('/auth/login', body: {'email': email, 'password': password});
    await _applyToken(Map<String, dynamic>.from(body));
  }

  Future<void> logout() async {
    api.token = null;
    user = null;
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
}
