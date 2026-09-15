import 'package:fl_chart/fl_chart.dart';
import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import 'package:url_launcher/url_launcher.dart';

import '../state.dart';
import '../widgets.dart';

const kMarketplaceLabel = {
  'EURO2': 'Euro2 coleccionistas',
  'EURO2_USER': 'compras de coleccionistas',
  'EBAY_ES': 'eBay España',
  'EBAY_DE': 'eBay Alemania',
  'EBAY_FR': 'eBay Francia',
  'EBAY_IT': 'eBay Italia',
  'EBAY_NL': 'eBay Países Bajos',
  'EBAY_AT': 'eBay Austria',
};

const kReasonLabel = {
  'lot': 'lote de varias monedas',
  'replica': 'réplica o fantasía',
  'altered': 'moneda alterada (chapada, coloreada)',
  'match_weak': 'no está claro que sea esta moneda',
  'match_medium': 'coincidencia probable',
  'below_face_value': 'por debajo del valor facial',
  'price_absurd': 'precio fuera de toda lógica',
  'year_mismatch': 'el año del anuncio no coincide',
  'certified': 'certificada (PCGS/NGC)',
};

String marketplaceName(String code) => kMarketplaceLabel[code] ?? code;

Future<void> openUrl(BuildContext context, String url) async {
  if (url.startsWith('euro2://')) {
    ScaffoldMessenger.of(context).showSnackBar(const SnackBar(
        content: Text('Anuncio entre coleccionistas: Mercado → Coleccionistas')));
    return;
  }
  final uri = Uri.parse(url);
  if (!await launchUrl(uri, mode: LaunchMode.externalApplication)) {
    if (context.mounted) showError(context, 'No se pudo abrir el enlace');
  }
}

/// Market intelligence for one coin type: range, band, verdict, chart, offers.
class MarketBlock extends StatefulWidget {
  const MarketBlock({super.key, required this.typeId, this.compact = false});
  final String typeId;
  final bool compact;

  @override
  State<MarketBlock> createState() => _MarketBlockState();
}

class _MarketBlockState extends State<MarketBlock> {
  Map<String, dynamic>? _m;
  Object? _error;
  bool _watching = false;
  bool _showIgnored = false;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    final state = context.read<AppState>();
    try {
      final m = Map<String, dynamic>.from(await state.api.get('/types/${widget.typeId}/market'));
      final watching = await state.isWatching(widget.typeId);
      if (mounted) {
        setState(() {
          _m = m;
          _watching = watching;
        });
      }
    } catch (e) {
      if (mounted) setState(() => _error = e);
    }
  }

  Future<void> _toggleWatch() async {
    final state = context.read<AppState>();
    if (!state.loggedIn) {
      showError(context, 'Inicia sesión para seguir esta moneda');
      return;
    }
    try {
      await state.setWatching(widget.typeId, !_watching);
      setState(() => _watching = !_watching);
    } catch (e) {
      if (mounted) showError(context, e);
    }
  }

  @override
  Widget build(BuildContext context) {
    if (_error != null) return ErrorBox(_error!, onRetry: _load);
    final m = _m;
    if (m == null) return const Padding(padding: EdgeInsets.all(16), child: LinearProgressIndicator());
    final realized = m['realized'] as Map<String, dynamic>?;
    final asking = m['asking'] as Map<String, dynamic>?;
    final band = Map<String, dynamic>.from(m['band']);
    final buy = Map<String, dynamic>.from(m['buy']);
    final offers = List<Map<String, dynamic>>.from(m['offers']);
    final ignored = List<Map<String, dynamic>>.from(m['ignored']);
    final external = List<Map<String, dynamic>>.from(m['external_links'] ?? []);
    final history = List<Map<String, dynamic>>.from(m['history']);
    final estimates = List<Map<String, dynamic>>.from(m['estimate_history']);
    final trend = m['trend_pct'] as num?;
    final scheme = Theme.of(context).colorScheme;

    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      Row(children: [
        Expanded(child: Text('Mercado', style: Theme.of(context).textTheme.titleMedium)),
        TextButton.icon(
          onPressed: _toggleWatch,
          icon: Icon(_watching ? Icons.visibility : Icons.visibility_outlined),
          label: Text(_watching ? 'Siguiendo' : 'Seguir'),
        ),
      ]),
      _VerdictCard(buy: buy, band: band, trend: trend, onOpen: (u) => openUrl(context, u)),
      const SizedBox(height: 8),
      Wrap(spacing: 8, runSpacing: 8, children: [
        _Stat('Rango justo', '${euro(band['low'])} – ${euro(band['high'])}',
            sub: kBasisLabel[band['basis']] ?? band['basis']),
        if (realized != null)
          _Stat('Vendidas', '${euro(realized['min'])} – ${euro(realized['max'])}',
              sub: 'mín. – máx. de ${realized['n']} ventas reales (${realized['window_days']} d)'),
        if (realized != null) _Stat('Mediana', euro(realized['median']), sub: 'ventas reales'),
        if (asking != null)
          _Stat('En venta ahora', '${euro(asking['min'])} – ${euro(asking['max'])}',
              sub: '${asking['n']} anuncios fiables'),
        if (trend != null)
          _Stat('Tendencia', '${trend >= 0 ? '+' : ''}${trend.toStringAsFixed(0)} %',
              sub: '90 días vs. resto del año', color: trend >= 0 ? Colors.green : Colors.red),
        if (m['expected_days_to_sell'] != null)
          _Stat('Liquidez', '~${m['expected_days_to_sell']} días',
              sub: '${(m['sales_per_month'] as num).toStringAsFixed(1)} ventas/mes'),
        if (m['best_marketplace'] != null)
          _Stat('Mejor plaza', marketplaceName(m['best_marketplace']), sub: 'mayor mediana de venta'),
      ]),
      const SizedBox(height: 12),
      if (history.any((h) => h['sold_n'] > 0 || h['ask_n'] > 0) || estimates.isNotEmpty) ...[
        Text('Evolución del precio', style: Theme.of(context).textTheme.titleSmall),
        SizedBox(height: 200, child: RepaintBoundary(child: PriceChart(history: history, estimates: estimates))),
        const _Legend(),
        const SizedBox(height: 12),
      ] else
        Padding(
          padding: const EdgeInsets.symmetric(vertical: 8),
          child: Text(
            'Sin ventas registradas todavía. El gráfico se rellena solo con las ventas observadas y con las compras que registran los coleccionistas.',
            style: TextStyle(fontSize: 12, color: scheme.outline),
          ),
        ),
      if (external.isNotEmpty) ...[
        Text('Ver en las plazas', style: Theme.of(context).textTheme.titleSmall),
        Wrap(spacing: 6, children: [
          for (final l in external)
            ActionChip(
              avatar: Icon(l['kind'] == 'sold' ? Icons.history : Icons.open_in_new, size: 16),
              label: Text(l['label'], style: const TextStyle(fontSize: 12)),
              onPressed: () => openUrl(context, l['url']),
            ),
        ]),
        const SizedBox(height: 8),
      ],
      if (!widget.compact) ...[
        if (offers.isNotEmpty) ...[
          Text('Anuncios fiables (${offers.length})', style: Theme.of(context).textTheme.titleSmall),
          for (final o in offers) _OfferTile(offer: o, onOpen: (u) => openUrl(context, u)),
        ],
        if (ignored.isNotEmpty)
          TextButton(
            onPressed: () => setState(() => _showIgnored = !_showIgnored),
            child: Text('${ignored.length} anuncios descartados ${_showIgnored ? '▲' : '▼'}'),
          ),
        if (_showIgnored)
          for (final i in ignored)
            ListTile(
              dense: true,
              leading: const Icon(Icons.block, size: 18),
              title: Text('${euro(i['price'])} · ${i['title']}', maxLines: 1, overflow: TextOverflow.ellipsis),
              subtitle: Text((i['reasons'] as List).map((r) => kReasonLabel[r] ?? r).join(', ')),
              onTap: () => openUrl(context, i['url']),
            ),
      ],
    ]);
  }
}

class _Stat extends StatelessWidget {
  const _Stat(this.label, this.value, {this.sub, this.color});
  final String label, value;
  final String? sub;
  final Color? color;

  @override
  Widget build(BuildContext context) => Container(
        width: 160,
        padding: const EdgeInsets.all(10),
        decoration: BoxDecoration(
          color: Theme.of(context).colorScheme.surfaceContainerHighest,
          borderRadius: BorderRadius.circular(10),
        ),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text(label, style: Theme.of(context).textTheme.labelSmall),
          Text(value, style: Theme.of(context).textTheme.titleMedium?.copyWith(color: color)),
          if (sub != null) Text(sub!, style: const TextStyle(fontSize: 10)),
        ]),
      );
}

class _VerdictCard extends StatelessWidget {
  const _VerdictCard({required this.buy, required this.band, required this.trend, required this.onOpen});
  final Map<String, dynamic> buy, band;
  final num? trend;
  final void Function(String) onOpen;

  @override
  Widget build(BuildContext context) {
    final verdict = buy['verdict'] as String;
    final cheapest = buy['cheapest'] as Map<String, dynamic>?;
    final (icon, color, title, body) = switch (verdict) {
      'buy_now' => (
          Icons.local_fire_department,
          Theme.of(context).colorScheme.tertiary,
          (buy['saving_pct'] as num) >= 15 ? 'Chollo: cómprala ahora' : 'Buen momento para comprar',
          'Hay una oferta fiable a ${euro(cheapest?['price'])}, un ${(buy['saving_pct'] as num).toStringAsFixed(0)} % por debajo del rango de ventas reales.'
        ),
      'fair' => (
          Icons.thumb_up,
          Theme.of(context).colorScheme.primary,
          'Precio justo',
          'La oferta más barata (${euro(cheapest?['price'])}) está dentro del rango de ventas reales.'
        ),
      'overpriced' => (
          Icons.trending_up,
          Theme.of(context).colorScheme.secondary,
          'Cara ahora mismo',
          'La oferta más barata (${euro(cheapest?['price'])}) supera el rango de ventas reales. Espera o negocia.'
        ),
      'wait' => (
          Icons.hourglass_bottom,
          Colors.orange,
          'Mejor esperar',
          'El precio está bajando (${trend?.toStringAsFixed(0)} % en 90 días) y la oferta actual no es un chollo.'
        ),
      _ => (
          Icons.search_off,
          Theme.of(context).colorScheme.outline,
          'Sin ofertas fiables ahora',
          'No hay anuncios fiables activos. Síguela y te avisamos cuando aparezca un chollo.'
        ),
    };
    return Card(
      color: color.withValues(alpha: 0.12),
      child: ListTile(
        leading: Icon(icon, color: color, size: 32),
        title: Text(title, style: TextStyle(color: color, fontWeight: FontWeight.bold)),
        subtitle: Text(body),
        trailing: cheapest != null
            ? FilledButton.tonal(onPressed: () => onOpen(cheapest['url']), child: const Text('Ver'))
            : null,
      ),
    );
  }
}

class _OfferTile extends StatelessWidget {
  const _OfferTile({required this.offer, required this.onOpen});
  final Map<String, dynamic> offer;
  final void Function(String) onOpen;

  @override
  Widget build(BuildContext context) {
    final discount = offer['discount_pct'] as num;
    final reasons = (offer['reasons'] as List).map((r) => kReasonLabel[r] ?? r).join(', ');
    return ListTile(
      dense: true,
      leading: Icon(offer['kind'] == 'auction_open' ? Icons.gavel : Icons.sell,
          color: discount > 0 ? Colors.green : null),
      title: Text('${euro(offer['price'])} · ${marketplaceName(offer['marketplace'])}'
          '${discount > 0 ? ' · −${discount.toStringAsFixed(0)} %' : ''}'),
      subtitle: Text('${offer['title']}${reasons.isNotEmpty ? '\n$reasons' : ''}',
          maxLines: 2, overflow: TextOverflow.ellipsis),
      trailing: const Icon(Icons.open_in_new, size: 18),
      onTap: () => onOpen(offer['url']),
    );
  }
}

class _Legend extends StatelessWidget {
  const _Legend();

  @override
  Widget build(BuildContext context) => Wrap(spacing: 12, children: const [
        _LegendItem(Colors.green, 'mediana de ventas'),
        _LegendItem(Colors.greenAccent, 'mín./máx. vendido'),
        _LegendItem(Colors.orange, 'precio pedido'),
        _LegendItem(Colors.blue, 'valor estimado'),
      ]);
}

class _LegendItem extends StatelessWidget {
  const _LegendItem(this.color, this.label);
  final Color color;
  final String label;

  @override
  Widget build(BuildContext context) => Row(mainAxisSize: MainAxisSize.min, children: [
        Container(width: 10, height: 10, color: color),
        const SizedBox(width: 4),
        Text(label, style: const TextStyle(fontSize: 10)),
      ]);
}

/// Monthly realized min/median/max, asking median, and the estimate trail.
class PriceChart extends StatefulWidget {
  const PriceChart({super.key, required this.history, required this.estimates});
  final List<Map<String, dynamic>> history;
  final List<Map<String, dynamic>> estimates;

  @override
  State<PriceChart> createState() => _PriceChartState();
}

class _PriceChartState extends State<PriceChart> {
  // Spots are parsed once per data set, not on every rebuild (tooltips rebuild the chart).
  late List<String> months;
  late List<FlSpot> median, minS, maxS, asks, est;

  @override
  void initState() {
    super.initState();
    _compute();
  }

  @override
  void didUpdateWidget(PriceChart old) {
    super.didUpdateWidget(old);
    if (old.history != widget.history || old.estimates != widget.estimates) _compute();
  }

  double? _d(dynamic v) => v == null ? null : double.tryParse(v.toString());

  void _compute() {
    final history = widget.history;
    months = history.map((h) => h['month'] as String).toList();
    List<FlSpot> spots(String key) => [
          for (var i = 0; i < history.length; i++)
            if (_d(history[i][key]) != null) FlSpot(i.toDouble(), _d(history[i][key])!),
        ];
    median = spots('sold_median');
    minS = spots('sold_min');
    maxS = spots('sold_max');
    asks = spots('ask_median');
    // estimate trail mapped onto the month axis by its date
    est = [];
    for (final e in widget.estimates) {
      final at = e['at'] as String;
      final idx = months.indexOf(at.substring(0, 7));
      final v = _d(e['median']);
      if (idx >= 0 && v != null) est.add(FlSpot(idx.toDouble(), v));
    }
  }

  @override
  Widget build(BuildContext context) {
    final history = widget.history;
    final all = [...median, ...minS, ...maxS, ...asks, ...est];
    if (all.isEmpty) return const SizedBox.shrink();
    final maxY = all.map((s) => s.y).reduce((a, b) => a > b ? a : b) * 1.15;
    return LineChart(LineChartData(
      minY: 0,
      maxY: maxY,
      minX: 0,
      maxX: (history.length - 1).toDouble(),
      lineTouchData: LineTouchData(
        touchTooltipData: LineTouchTooltipData(
          getTooltipItems: (touched) => [
            for (final t in touched)
              LineTooltipItem('${months[t.x.toInt()]}: ${t.y.toStringAsFixed(2)} €',
                  TextStyle(color: t.bar.color ?? Colors.white, fontSize: 11)),
          ],
        ),
      ),
      titlesData: FlTitlesData(
        topTitles: const AxisTitles(),
        rightTitles: const AxisTitles(),
        leftTitles: AxisTitles(
            sideTitles: SideTitles(
                showTitles: true,
                reservedSize: 36,
                getTitlesWidget: (v, _) => Text('${v.toStringAsFixed(0)} €', style: const TextStyle(fontSize: 9)))),
        bottomTitles: AxisTitles(
          sideTitles: SideTitles(
            showTitles: true,
            interval: (history.length / 6).ceilToDouble(),
            getTitlesWidget: (v, _) {
              final i = v.toInt();
              if (i < 0 || i >= months.length) return const SizedBox.shrink();
              return Text(months[i].substring(2).replaceAll('-', '/'), style: const TextStyle(fontSize: 9));
            },
          ),
        ),
      ),
      gridData: const FlGridData(drawVerticalLine: false),
      borderData: FlBorderData(show: false),
      lineBarsData: [
        if (maxS.isNotEmpty)
          LineChartBarData(spots: maxS, color: Colors.greenAccent, barWidth: 1, dotData: const FlDotData(show: false), dashArray: [4, 4]),
        if (minS.isNotEmpty)
          LineChartBarData(spots: minS, color: Colors.greenAccent, barWidth: 1, dotData: const FlDotData(show: false), dashArray: [4, 4]),
        if (median.isNotEmpty)
          LineChartBarData(spots: median, color: Colors.green, barWidth: 2.5, isCurved: false),
        if (asks.isNotEmpty)
          LineChartBarData(spots: asks, color: Colors.orange, barWidth: 1.5, dotData: const FlDotData(show: false)),
        if (est.isNotEmpty)
          LineChartBarData(spots: est, color: Colors.blue, barWidth: 2, dotData: const FlDotData(show: false), isStepLineChart: true),
      ],
    ));
  }
}
