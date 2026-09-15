import 'package:flutter/material.dart';

import 'api.dart';

const kCountryNames = {
  'AD': 'Andorra', 'AT': 'Austria', 'BE': 'Bélgica', 'BG': 'Bulgaria', 'CY': 'Chipre',
  'DE': 'Alemania', 'EE': 'Estonia', 'ES': 'España', 'FI': 'Finlandia', 'FR': 'Francia',
  'GR': 'Grecia', 'HR': 'Croacia', 'IE': 'Irlanda', 'IT': 'Italia', 'LT': 'Lituania',
  'LU': 'Luxemburgo', 'LV': 'Letonia', 'MC': 'Mónaco', 'MT': 'Malta', 'NL': 'Países Bajos',
  'PT': 'Portugal', 'SI': 'Eslovenia', 'SK': 'Eslovaquia', 'SM': 'San Marino', 'VA': 'Vaticano',
};

String countryName(String? code) => kCountryNames[code] ?? (code ?? '');

const kBasisLabel = {
  'sold': 'ventas reales',
  'catalog': 'valor de catálogo',
  'asking_only': 'precios pedidos',
  'mintage_model': 'estimación por tirada',
  'face_value': 'valor facial',
  'insufficient': 'sin datos',
};

const kBasisShort = {
  'sold': 'ventas',
  'catalog': 'catálogo',
  'asking_only': 'pedido',
  'mintage_model': 'est. tirada',
  'face_value': 'facial',
};

/// "3,50 – 12 €" style range for list rows; collapses when both ends coincide.
String euroRange(dynamic low, dynamic high) {
  if (low == null || high == null) return '—';
  final l = double.tryParse(low.toString()) ?? 0;
  final h = double.tryParse(high.toString()) ?? 0;
  String f(double v) => v >= 100 ? v.toStringAsFixed(0) : v.toStringAsFixed(2).replaceAll('.', ',');
  return l == h ? '${f(l)} €' : '${f(l)} – ${f(h)} €';
}

const kTierLabel = {
  'exceptional': 'Excepcional',
  'very_rare': 'Muy rara',
  'rare': 'Rara',
  'uncommon': 'Poco común',
  'common': 'Común',
};

const kFinishLabel = {'circulation': 'Circulación', 'bu': 'BU', 'proof': 'Proof'};
const kPackagingLabel = {'loose': 'suelta', 'coincard': 'coincard', 'set': 'estuche'};
const kGradeLabel = {
  'unknown': 'sin grado',
  'circulated': 'circulada',
  'unc': 'sin circular',
  'bu': 'BU',
  'proof': 'proof',
};

Color tierColor(String? tier, ColorScheme scheme) => switch (tier) {
      'exceptional' => const Color(0xFF7B1FA2),
      'very_rare' => const Color(0xFFC62828),
      'rare' => const Color(0xFFEF6C00),
      'uncommon' => const Color(0xFF2E7D32),
      _ => scheme.outline,
    };

String euro(dynamic value) {
  if (value == null) return '—';
  final n = value is num ? value.toDouble() : double.tryParse(value.toString()) ?? 0;
  return '${n.toStringAsFixed(2).replaceAll('.', ',')} €';
}

class CoinThumb extends StatelessWidget {
  const CoinThumb({super.key, required this.api, required this.image, this.size = 56});

  final Euro2Api api;
  final Map<String, dynamic>? image;
  final double size;

  @override
  Widget build(BuildContext context) {
    final url = image?['url'] as String?;
    final borrowed = image?['borrowed'] == true;
    final thumb = ClipOval(
      child: SizedBox(
        width: size,
        height: size,
        child: url == null
            ? Tooltip(
                message: 'Sin foto oficial todavía (el BCE aún no la ha publicado)',
                child: Container(
                  color: Theme.of(context).colorScheme.surfaceContainerHighest,
                  child: Icon(Icons.hide_image_outlined, size: size * 0.45),
                ),
              )
            : _networkThumb(context, url),
      ),
    );
    if (!borrowed) return RepaintBoundary(child: thumb);
    // The photo is of the plain design this edition derives from (coloured, hologram, error).
    return Tooltip(
      message: 'Foto del diseño base; esta edición es especial',
      child: Stack(children: [
        Opacity(opacity: 0.75, child: thumb),
        Positioned(
          right: 0,
          bottom: 0,
          child: Icon(Icons.auto_fix_high, size: size * 0.3, color: Theme.of(context).colorScheme.primary),
        ),
      ]),
    );
  }

  /// Ask the server for a thumbnail sized for this widget and decode it at that size: a phone
  /// list with fifty 1000 px JPEGs decoded on the main thread is what "low fps" looks like.
  Widget _networkThumb(BuildContext context, String url) {
    final px = (size * MediaQuery.devicePixelRatioOf(context)).ceil();
    return Image.network(
      '${api.imageUrl(url)}?w=$px',
      fit: BoxFit.cover,
      cacheWidth: px,
      cacheHeight: px,
      filterQuality: FilterQuality.medium,
      gaplessPlayback: true,
      errorBuilder: (_, _, _) => const Icon(Icons.euro),
    );
  }
}

class Chip2 extends StatelessWidget {
  const Chip2(this.label, {super.key, this.color});
  final String label;
  final Color? color;

  @override
  Widget build(BuildContext context) {
    final c = color ?? Theme.of(context).colorScheme.secondaryContainer;
    return Container(
      margin: const EdgeInsets.only(right: 6, top: 4),
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
      decoration: BoxDecoration(color: c.withValues(alpha: 0.18), borderRadius: BorderRadius.circular(12),
          border: Border.all(color: c.withValues(alpha: 0.6))),
      child: Text(label, style: Theme.of(context).textTheme.labelSmall),
    );
  }
}

class ErrorBox extends StatelessWidget {
  const ErrorBox(this.error, {super.key, this.onRetry});
  final Object error;
  final VoidCallback? onRetry;

  @override
  Widget build(BuildContext context) => Center(
        child: Padding(
          padding: const EdgeInsets.all(24),
          child: Column(mainAxisSize: MainAxisSize.min, children: [
            const Icon(Icons.cloud_off, size: 40),
            const SizedBox(height: 8),
            Text('$error', textAlign: TextAlign.center),
            if (onRetry != null) TextButton(onPressed: onRetry, child: const Text('Reintentar')),
          ]),
        ),
      );
}

Future<void> showError(BuildContext context, Object error) async {
  if (!context.mounted) return;
  ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('$error')));
}

class TypeTile extends StatelessWidget {
  const TypeTile({super.key, required this.api, required this.type, this.trailing, this.onTap});
  final Euro2Api api;
  final Map<String, dynamic> type;
  final Widget? trailing;
  final VoidCallback? onTap;

  @override
  Widget build(BuildContext context) {
    final value = type['value'] as Map<String, dynamic>?;
    return ListTile(
      leading: CoinThumb(api: api, image: type['image']),
      title: Text(type['title'] ?? '${countryName(type['country_code'])} ${type['year']}',
          maxLines: 2, overflow: TextOverflow.ellipsis),
      subtitle: Text('${countryName(type['country_code'])} · ${type['year']}'
          '${type['kind'] == 'circulation' ? ' · circulación' : ''}'
          '${type['kind'] == 'error' ? ' · error de acuñación' : ''}'
          '${type['mintage_total'] != null ? ' · tirada ${_fmtInt(type['mintage_total'])}' : ''}'),
      trailing: trailing ?? (value == null ? null : ValueBadge(value: value)),
      onTap: onTap,
    );
  }
}

/// Value range with its basis, compact enough for a list row.
class ValueBadge extends StatelessWidget {
  const ValueBadge({super.key, required this.value});
  final Map<String, dynamic> value;

  @override
  Widget build(BuildContext context) {
    final basis = value['basis'] as String;
    final color = switch (basis) {
      'sold' => Colors.green,
      'catalog' => Colors.blue,
      'mintage_model' => Theme.of(context).colorScheme.outline,
      _ => Colors.orange,
    };
    return Column(mainAxisAlignment: MainAxisAlignment.center, crossAxisAlignment: CrossAxisAlignment.end, children: [
      Text(euroRange(value['low'], value['high']),
          style: Theme.of(context).textTheme.titleSmall?.copyWith(color: color, fontWeight: FontWeight.bold)),
      Text(kBasisShort[basis] ?? basis, style: TextStyle(fontSize: 10, color: color)),
    ]);
  }
}

String _fmtInt(dynamic n) {
  final s = n.toString();
  final buf = StringBuffer();
  for (var i = 0; i < s.length; i++) {
    if (i > 0 && (s.length - i) % 3 == 0) buf.write('.');
    buf.write(s[i]);
  }
  return buf.toString();
}

String fmtInt(dynamic n) => n == null ? '—' : _fmtInt(n);

/// A list whose header/footer widgets are cheap and whose rows are built on demand, so a
/// tab with fifty cards does not lay out fifty cards (and their thumbnails) at once.
class SectionList extends StatelessWidget {
  const SectionList({
    super.key,
    this.padding = const EdgeInsets.all(12),
    this.header = const [],
    this.footer = const [],
    required this.itemCount,
    required this.itemBuilder,
  });

  final EdgeInsetsGeometry padding;
  final List<Widget> header;
  final List<Widget> footer;
  final int itemCount;
  final Widget Function(BuildContext context, int index) itemBuilder;

  @override
  Widget build(BuildContext context) => ListView.builder(
        padding: padding,
        itemCount: header.length + itemCount + footer.length,
        itemBuilder: (context, i) {
          if (i < header.length) return header[i];
          final j = i - header.length;
          if (j < itemCount) return itemBuilder(context, j);
          return footer[j - itemCount];
        },
      );
}
