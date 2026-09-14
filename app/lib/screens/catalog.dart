import 'dart:async';

import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../state.dart';
import '../widgets.dart';
import 'coin_detail.dart';

class CatalogScreen extends StatefulWidget {
  const CatalogScreen({super.key});

  @override
  State<CatalogScreen> createState() => _CatalogScreenState();
}

class _CatalogScreenState extends State<CatalogScreen> {
  final _query = TextEditingController();
  String? _country;
  int? _year;
  bool _semantic = false;
  List<Map<String, dynamic>> _items = [];
  int _total = 0;
  bool _loading = false;
  Object? _error;
  Timer? _debounce;

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void dispose() {
    _debounce?.cancel();
    _query.dispose();
    super.dispose();
  }

  void _onChanged(String _) {
    _debounce?.cancel();
    _debounce = Timer(const Duration(milliseconds: 450), _load);
  }

  Future<void> _load() async {
    final api = context.read<AppState>().api;
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final q = _query.text.trim();
      if (q.isNotEmpty && _semantic) {
        final hits = List<Map<String, dynamic>>.from(await api.get('/search/semantic', {'q': q, 'limit': '30'}));
        _items = hits.map((h) => Map<String, dynamic>.from(h['type'])).toList();
        _total = _items.length;
      } else if (q.isNotEmpty) {
        final page = await api.get('/search', {'q': q, 'limit': '50'});
        _items = List<Map<String, dynamic>>.from(page['items']);
        _total = page['total'];
      } else {
        final page = await api.get('/types', {
          'limit': '60',
          if (_country case final c?) 'country': c,
          if (_year != null) 'year': '$_year',
        });
        _items = List<Map<String, dynamic>>.from(page['items']);
        _total = page['total'];
      }
    } catch (e) {
      _error = e;
    }
    if (mounted) setState(() => _loading = false);
  }

  @override
  Widget build(BuildContext context) {
    final api = context.read<AppState>().api;
    final years = [for (var y = DateTime.now().year; y >= 2004; y--) y];
    return Scaffold(
      appBar: AppBar(title: const Text('Catálogo 2 €')),
      body: Column(children: [
        Padding(
          padding: const EdgeInsets.fromLTRB(12, 8, 12, 0),
          child: TextField(
            controller: _query,
            textInputAction: TextInputAction.search,
            onChanged: _onChanged,
            onSubmitted: (_) => _load(),
            decoration: InputDecoration(
              hintText: _semantic ? 'Describe la moneda: "un puente y un río"' : 'Buscar por título…',
              prefixIcon: IconButton(icon: const Icon(Icons.search), onPressed: _load),
              suffixIcon: IconButton(
                tooltip: _semantic ? 'Búsqueda semántica activada' : 'Activar búsqueda semántica',
                icon: Icon(_semantic ? Icons.auto_awesome : Icons.auto_awesome_outlined),
                onPressed: () => setState(() => _semantic = !_semantic),
              ),
              border: const OutlineInputBorder(),
            ),
          ),
        ),
        SingleChildScrollView(
          scrollDirection: Axis.horizontal,
          padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
          child: Row(children: [
            DropdownButton<String?>(
              value: _country,
              hint: const Text('País'),
              items: [
                const DropdownMenuItem(value: null, child: Text('Todos los países')),
                for (final e in kCountryNames.entries)
                  DropdownMenuItem(value: e.key, child: Text(e.value)),
              ],
              onChanged: (v) {
                setState(() => _country = v);
                _load();
              },
            ),
            const SizedBox(width: 12),
            DropdownButton<int?>(
              value: _year,
              hint: const Text('Año'),
              items: [
                const DropdownMenuItem(value: null, child: Text('Todos los años')),
                for (final y in years) DropdownMenuItem(value: y, child: Text('$y')),
              ],
              onChanged: (v) {
                setState(() => _year = v);
                _load();
              },
            ),
            const SizedBox(width: 12),
            Text('$_total resultados', style: Theme.of(context).textTheme.labelMedium),
          ]),
        ),
        Expanded(
          child: _loading
              ? const Center(child: CircularProgressIndicator())
              : _error != null
                  ? ErrorBox(_error!, onRetry: _load)
                  : ListView.separated(
                      itemCount: _items.length,
                      separatorBuilder: (_, _) => const Divider(height: 1),
                      itemBuilder: (_, i) => TypeTile(
                        api: api,
                        type: _items[i],
                        onTap: () => Navigator.of(context).push(MaterialPageRoute(
                            builder: (_) => CoinDetailScreen(typeId: _items[i]['id']))),
                      ),
                    ),
        ),
      ]),
    );
  }
}
