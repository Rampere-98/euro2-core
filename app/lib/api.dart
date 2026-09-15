import 'dart:convert';
import 'dart:typed_data';

import 'package:http/http.dart' as http;

import 'device.dart';

/// Thin client over the euro2-core REST API.
class Euro2Api {
  Euro2Api({required this.baseUrl, this.token, this.lang = 'es'});

  String baseUrl;
  String? token;
  String lang;

  Map<String, String> get _headers => {
        'Accept-Language': lang,
        // anonymous device kind, so the server can adapt and count usage per platform
        'X-Euro2-Device': Device.kind.name,
        'X-Euro2-Pwa': Device.isPwa ? '1' : '0',
        if (token != null) 'Authorization': 'Bearer $token',
      };

  Uri _uri(String path, [Map<String, String>? query]) =>
      Uri.parse('$baseUrl$path').replace(queryParameters: query);

  Future<dynamic> _json(http.Response r) async {
    if (r.statusCode >= 400) {
      String detail;
      try {
        detail = jsonDecode(utf8.decode(r.bodyBytes))['detail'].toString();
      } catch (_) {
        detail = r.body;
      }
      throw ApiException(r.statusCode, detail);
    }
    if (r.bodyBytes.isEmpty) return null;
    return jsonDecode(utf8.decode(r.bodyBytes));
  }

  Future<dynamic> get(String path, [Map<String, String>? query]) async =>
      _json(await http.get(_uri(path, query), headers: _headers));

  Future<dynamic> post(String path, {Object? body}) async => _json(await http.post(
        _uri(path),
        headers: {..._headers, 'Content-Type': 'application/json'},
        body: body == null ? null : jsonEncode(body),
      ));

  Future<dynamic> put(String path, {Object? body}) async => _json(await http.put(
        _uri(path),
        headers: {..._headers, 'Content-Type': 'application/json'},
        body: jsonEncode(body),
      ));

  Future<dynamic> patch(String path, {Object? body}) async => _json(await http.patch(
        _uri(path),
        headers: {..._headers, 'Content-Type': 'application/json'},
        body: jsonEncode(body),
      ));

  Future<dynamic> delete(String path) async =>
      _json(await http.delete(_uri(path), headers: _headers));

  Future<dynamic> upload(String path, Uint8List bytes, String filename,
      {Map<String, String>? fields}) async {
    final req = http.MultipartRequest('POST', _uri(path))
      ..headers.addAll(_headers)
      ..files.add(http.MultipartFile.fromBytes('file', bytes, filename: filename));
    if (fields != null) req.fields.addAll(fields);
    final streamed = await req.send();
    return _json(await http.Response.fromStream(streamed));
  }

  String imageUrl(String? relative) => relative == null ? '' : '$baseUrl$relative';
}

class ApiException implements Exception {
  ApiException(this.status, this.detail);
  final int status;
  final String detail;

  @override
  String toString() => detail;
}
