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
  'face_value': 'valor facial',
  'insufficient': 'sin datos',
};

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
            : Image.network(api.imageUrl(url), fit: BoxFit.cover,
                errorBuilder: (_, _, _) => const Icon(Icons.euro)),
      ),
    );
    if (!borrowed) return thumb;
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
  Widget build(BuildContext context) => ListTile(
        leading: CoinThumb(api: api, image: type['image']),
        title: Text(type['title'] ?? '${countryName(type['country_code'])} ${type['year']}',
            maxLines: 2, overflow: TextOverflow.ellipsis),
        subtitle: Text('${countryName(type['country_code'])} · ${type['year']}'
            '${type['kind'] == 'circulation' ? ' · circulación' : ''}'
            '${type['kind'] == 'error' ? ' · error de acuñación' : ''}'
            '${type['mintage_total'] != null ? ' · tirada ${_fmtInt(type['mintage_total'])}' : ''}'),
        trailing: trailing,
        onTap: onTap,
      );
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
