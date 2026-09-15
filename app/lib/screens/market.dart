import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:provider/provider.dart';

import '../state.dart';
import '../widgets.dart';
import '../widgets/market_block.dart';
import 'coin_detail.dart';

/// The market assistant: deals, buy advice, sell advice, watchlist. Informational only.
class MarketScreen extends StatelessWidget {
  const MarketScreen({super.key});

  @override
  Widget build(BuildContext context) => DefaultTabController(
        length: 4,
        child: Scaffold(
          appBar: AppBar(
            title: const Text('Asistente de mercado'),
            bottom: const TabBar(isScrollable: true, tabs: [
              Tab(icon: Icon(Icons.local_fire_department), text: 'Chollos'),
              Tab(icon: Icon(Icons.shopping_cart), text: 'Comprar'),
              Tab(icon: Icon(Icons.sell), text: 'Vender'),
              Tab(icon: Icon(Icons.visibility), text: 'Seguimiento'),
            ]),
          ),
          body: const TabBarView(children: [
            _DealsTab(),
            _BuyTab(),
            _SellTab(),
            _WatchTab(),
          ]),
        ),
      );
}

// ------------------------------------------------------------------ Chollos

class _DealsTab extends StatefulWidget {
  const _DealsTab();

  @override
  State<_DealsTab> createState() => _DealsTabState();
}

class _DealsTabState extends State<_DealsTab> with AutomaticKeepAliveClientMixin {
  List<Map<String, dynamic>> _deals = [];
  List<Map<String, dynamic>> _movers = [];
  bool _loading = true;
  Object? _error;

  @override
  bool get wantKeepAlive => true;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    final api = context.read<AppState>().api;
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      _deals = List<Map<String, dynamic>>.from(await api.get('/market/deals', {'limit': '50'}));
      _movers = List<Map<String, dynamic>>.from(await api.get('/market/movers', {'limit': '10'}));
    } catch (e) {
      _error = e;
    }
    if (mounted) setState(() => _loading = false);
  }

  @override
  Widget build(BuildContext context) {
    super.build(context);
    final api = context.read<AppState>().api;
    if (_loading) return const Center(child: CircularProgressIndicator());
    if (_error != null) return ErrorBox(_error!, onRetry: _load);
    return RefreshIndicator(
      onRefresh: _load,
      child: ListView(padding: const EdgeInsets.all(12), children: [
        const Text(
          'Anuncios fiables al menos un 15 % por debajo del rango de ventas reales. Lotes, réplicas y monedas alteradas quedan fuera.',
          style: TextStyle(fontSize: 12),
        ),
        const SizedBox(height: 8),
        if (_deals.isEmpty)
          const Card(
            child: Padding(
              padding: EdgeInsets.all(16),
              child: Text('Ahora mismo no hay chollos detectados. El mercado se revisa cada pocas horas; '
                  'sigue tus monedas y te avisamos.'),
            ),
          ),
        for (final d in _deals)
          Card(
            child: Column(children: [
              TypeTile(
                api: api,
                type: Map<String, dynamic>.from(d['type']),
                trailing: Column(mainAxisAlignment: MainAxisAlignment.center, crossAxisAlignment: CrossAxisAlignment.end, children: [
                  Text(euro(d['listing']['price']), style: Theme.of(context).textTheme.titleMedium),
                  Text('−${(d['listing']['discount_pct'] as num).toStringAsFixed(0)} %',
                      style: const TextStyle(color: Colors.green, fontWeight: FontWeight.bold)),
                ]),
                onTap: () => Navigator.of(context).push(
                    MaterialPageRoute(builder: (_) => CoinDetailScreen(typeId: d['type']['id']))),
              ),
              Padding(
                padding: const EdgeInsets.fromLTRB(16, 0, 8, 6),
                child: Row(children: [
                  Expanded(
                    child: Text(
                      'rango real ${euro(d['band']['low'])} – ${euro(d['band']['high'])} · ${marketplaceName(d['listing']['marketplace'])}',
                      style: const TextStyle(fontSize: 12),
                    ),
                  ),
                  FilledButton.tonal(
                      onPressed: () => openUrl(context, d['listing']['url']), child: const Text('Ir al anuncio')),
                ]),
              ),
            ]),
          ),
        if (_movers.isNotEmpty) ...[
          const SizedBox(height: 12),
          Text('Las que más se mueven', style: Theme.of(context).textTheme.titleMedium),
          for (final m in _movers)
            TypeTile(
              api: api,
              type: Map<String, dynamic>.from(m['type']),
              trailing: Text(
                '${(m['trend_pct'] as num) >= 0 ? '+' : ''}${(m['trend_pct'] as num).toStringAsFixed(0)} %',
                style: TextStyle(
                    color: (m['trend_pct'] as num) >= 0 ? Colors.green : Colors.red, fontWeight: FontWeight.bold),
              ),
              onTap: () => Navigator.of(context).push(
                  MaterialPageRoute(builder: (_) => CoinDetailScreen(typeId: m['type']['id']))),
            ),
        ],
      ]),
    );
  }
}

// ------------------------------------------------------------------ Comprar

class _BuyTab extends StatefulWidget {
  const _BuyTab();

  @override
  State<_BuyTab> createState() => _BuyTabState();
}

class _BuyTabState extends State<_BuyTab> with AutomaticKeepAliveClientMixin {
  final _query = TextEditingController();
  List<Map<String, dynamic>> _results = [];
  String? _selected;

  @override
  bool get wantKeepAlive => true;

  Future<void> _search() async {
    final api = context.read<AppState>().api;
    final q = _query.text.trim();
    if (q.length < 2) return;
    try {
      final page = await api.get('/search', {'q': q, 'limit': '20'});
      setState(() {
        _results = List<Map<String, dynamic>>.from(page['items']);
        _selected = null;
      });
    } catch (e) {
      if (mounted) showError(context, e);
    }
  }

  @override
  Widget build(BuildContext context) {
    super.build(context);
    final api = context.read<AppState>().api;
    return ListView(padding: const EdgeInsets.all(12), children: [
      TextField(
        controller: _query,
        onSubmitted: (_) => _search(),
        decoration: InputDecoration(
          hintText: '¿Qué moneda quieres comprar?',
          prefixIcon: IconButton(icon: const Icon(Icons.search), onPressed: _search),
          border: const OutlineInputBorder(),
        ),
      ),
      const SizedBox(height: 8),
      if (_selected == null)
        for (final t in _results)
          TypeTile(api: api, type: t, onTap: () => setState(() => _selected = t['id']))
      else ...[
        TextButton.icon(
            onPressed: () => setState(() => _selected = null),
            icon: const Icon(Icons.arrow_back),
            label: const Text('Otra moneda')),
        MarketBlock(typeId: _selected!),
      ],
      if (_results.isEmpty && _selected == null)
        const Padding(
          padding: EdgeInsets.all(16),
          child: Text('Busca una moneda y te diremos si el precio actual es un chollo, justo o caro, '
              'con enlaces directos a los anuncios fiables.'),
        ),
    ]);
  }
}

// ------------------------------------------------------------------ Vender

class _SellTab extends StatefulWidget {
  const _SellTab();

  @override
  State<_SellTab> createState() => _SellTabState();
}

class _SellTabState extends State<_SellTab> with AutomaticKeepAliveClientMixin {
  List<Map<String, dynamic>> _items = [];
  final Map<String, Map<String, dynamic>> _advice = {};
  bool _loading = true;
  Object? _error;

  @override
  bool get wantKeepAlive => true;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    final state = context.read<AppState>();
    if (!state.loggedIn) {
      setState(() => _loading = false);
      return;
    }
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final col = await state.api.get('/me/collection');
      _items = List<Map<String, dynamic>>.from(col['items']);
      for (final it in _items) {
        _advice[it['id']] =
            Map<String, dynamic>.from(await state.api.get('/me/collection/${it['id']}/sell-advice'));
      }
    } catch (e) {
      _error = e;
    }
    if (mounted) setState(() => _loading = false);
  }

  Future<void> _showCopy(Map<String, dynamic> advice) async {
    final copy = Map<String, dynamic>.from(advice['listing_copy']);
    final links = List<Map<String, dynamic>>.from(advice['external_links']);
    await showModalBottomSheet(
      context: context,
      showDragHandle: true,
      isScrollControlled: true,
      builder: (ctx) => DraggableScrollableSheet(
        expand: false,
        initialChildSize: 0.8,
        builder: (_, controller) => ListView(controller: controller, padding: const EdgeInsets.all(16), children: [
          Text('Texto para tu anuncio', style: Theme.of(ctx).textTheme.titleMedium),
          const Text('Generado aquí con los datos del catálogo. Pégalo donde vendas.', style: TextStyle(fontSize: 12)),
          for (final lang in const ['es', 'en', 'de'])
            if (copy[lang] case final c?)
              Card(
                child: Padding(
                  padding: const EdgeInsets.all(12),
                  child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                    Row(children: [
                      Expanded(child: Text(c['title'], style: const TextStyle(fontWeight: FontWeight.bold))),
                      IconButton(
                        tooltip: 'Copiar',
                        icon: const Icon(Icons.copy),
                        onPressed: () {
                          Clipboard.setData(ClipboardData(text: '${c['title']}\n\n${c['body']}'));
                          ScaffoldMessenger.of(ctx).showSnackBar(const SnackBar(content: Text('Copiado')));
                        },
                      ),
                    ]),
                    SelectableText(c['body'], style: const TextStyle(fontSize: 13)),
                  ]),
                ),
              ),
          const SizedBox(height: 8),
          Text('Dónde venderla', style: Theme.of(ctx).textTheme.titleMedium),
          const Text('Compara antes con las ventas cerradas de cada plaza:', style: TextStyle(fontSize: 12)),
          Wrap(spacing: 6, children: [
            for (final l in links)
              ActionChip(
                avatar: Icon(l['kind'] == 'sold' ? Icons.history : Icons.open_in_new, size: 16),
                label: Text(l['label']),
                onPressed: () => openUrl(ctx, l['url']),
              ),
          ]),
        ]),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    super.build(context);
    final state = context.watch<AppState>();
    if (!state.loggedIn) {
      return const Center(
          child: Padding(
              padding: EdgeInsets.all(24),
              child: Text('Inicia sesión y añade tus monedas: te diremos a cuánto venderlas, dónde, cuánto te queda neto y el texto del anuncio.',
                  textAlign: TextAlign.center)));
    }
    if (_loading) return const Center(child: CircularProgressIndicator());
    if (_error != null) return ErrorBox(_error!, onRetry: _load);
    final api = state.api;
    return RefreshIndicator(
      onRefresh: _load,
      child: ListView(padding: const EdgeInsets.all(12), children: [
        if (_items.isEmpty)
          const Padding(padding: EdgeInsets.all(16), child: Text('Tu colección está vacía.')),
        for (final it in _items)
          if (_advice[it['id']] case final a?)
            Card(
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                TypeTile(
                  api: api,
                  type: Map<String, dynamic>.from(it['type']),
                  trailing: Text(euro(a['start']), style: Theme.of(context).textTheme.titleMedium),
                  onTap: () => Navigator.of(context).push(
                      MaterialPageRoute(builder: (_) => CoinDetailScreen(typeId: it['type']['id']))),
                ),
                Padding(
                  padding: const EdgeInsets.fromLTRB(16, 0, 16, 8),
                  child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                    Text('Pide ${euro(a['start'])}, no bajes de ${euro(a['floor'])} '
                        '(${kGradeLabel[a['grade']] ?? a['grade']}; base: ${kBasisLabel[a['band']['basis']] ?? a['band']['basis']})'),
                    Text(
                      'Neto en eBay ≈ ${euro(a['net_ebay'])} (tras comisiones); en venta directa ${euro(a['net_euro2'])}'
                      '${a['expected_days'] != null ? ' · ~${a['expected_days']} días para vender' : ''}'
                      '${a['best_marketplace'] != null ? ' · mejor plaza: ${marketplaceName(a['best_marketplace'])}' : ''}',
                      style: const TextStyle(fontSize: 12),
                    ),
                    if (a['hold'] == true)
                      const Text('Está subiendo: si no tienes prisa, espera.',
                          style: TextStyle(fontSize: 12, color: Colors.green)),
                    if (a['realized'] != null)
                      Text(
                        'Ventas reales: ${euro(a['realized']['min'])} – ${euro(a['realized']['max'])} (${a['realized']['n']})',
                        style: const TextStyle(fontSize: 12),
                      ),
                    Align(
                      alignment: Alignment.centerRight,
                      child: FilledButton.tonal(
                          onPressed: () => _showCopy(a),
                          child: const Text('Texto del anuncio y dónde vender')),
                    ),
                  ]),
                ),
              ]),
            ),
      ]),
    );
  }
}

// ------------------------------------------------------------------ Seguimiento

class _WatchTab extends StatefulWidget {
  const _WatchTab();

  @override
  State<_WatchTab> createState() => _WatchTabState();
}

class _WatchTabState extends State<_WatchTab> with AutomaticKeepAliveClientMixin {
  List<Map<String, dynamic>> _rows = [];
  bool _loading = true;
  Object? _error;

  @override
  bool get wantKeepAlive => true;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    final state = context.read<AppState>();
    if (!state.loggedIn) {
      setState(() => _loading = false);
      return;
    }
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      _rows = List<Map<String, dynamic>>.from(await state.api.get('/me/watchlist'));
    } catch (e) {
      _error = e;
    }
    if (mounted) setState(() => _loading = false);
  }

  @override
  Widget build(BuildContext context) {
    super.build(context);
    final state = context.watch<AppState>();
    if (!state.loggedIn) {
      return const Center(
          child: Padding(
              padding: EdgeInsets.all(24),
              child: Text('Inicia sesión y pulsa "Seguir" en cualquier moneda: recibirás un aviso con cada chollo y cada movimiento de precio.',
                  textAlign: TextAlign.center)));
    }
    if (_loading) return const Center(child: CircularProgressIndicator());
    if (_error != null) return ErrorBox(_error!, onRetry: _load);
    return RefreshIndicator(
      onRefresh: _load,
      child: ListView(padding: const EdgeInsets.all(12), children: [
        if (_rows.isEmpty)
          const Padding(padding: EdgeInsets.all(16), child: Text('Todavía no sigues ninguna moneda.')),
        for (final w in _rows)
          Card(
            child: TypeTile(
              api: state.api,
              type: Map<String, dynamic>.from(w['type']),
              trailing: _verdictChip(w['buy']['verdict']),
              onTap: () => Navigator.of(context).push(
                  MaterialPageRoute(builder: (_) => CoinDetailScreen(typeId: w['type']['id']))),
            ),
          ),
      ]),
    );
  }

  Widget _verdictChip(String v) => switch (v) {
        'buy_now' => const Chip2('chollo', color: Colors.green),
        'fair' => const Chip2('precio justo', color: Colors.blue),
        'overpriced' => const Chip2('cara', color: Colors.orange),
        'wait' => const Chip2('esperar', color: Colors.orange),
        _ => const Chip2('sin ofertas'),
      };
}
