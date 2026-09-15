import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../install.dart';
import '../state.dart';
import '../widgets.dart';
import '../widgets/market_block.dart';
import 'admin.dart';

/// Ajustes: device preferences for everyone; server administration for the owner.
class SettingsScreen extends StatefulWidget {
  const SettingsScreen({super.key});

  @override
  State<SettingsScreen> createState() => _SettingsScreenState();
}

class _SettingsScreenState extends State<SettingsScreen> {
  String? _health;

  Future<void> _editServer() async {
    final state = context.read<AppState>();
    final ctrl = TextEditingController(text: state.api.baseUrl);
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Servidor'),
        content: TextField(
          controller: ctrl,
          decoration: InputDecoration(hintText: state.defaultBaseUrl, labelText: 'URL de la API'),
        ),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('Cancelar')),
          TextButton(
              onPressed: () {
                ctrl.text = '';
                Navigator.pop(ctx, true);
              },
              child: const Text('Restablecer')),
          FilledButton(onPressed: () => Navigator.pop(ctx, true), child: const Text('Guardar')),
        ],
      ),
    );
    if (ok == true) {
      await state.setBaseUrl(ctrl.text);
      await _test();
    }
  }

  Future<void> _test() async {
    final api = context.read<AppState>().api;
    setState(() => _health = 'probando…');
    try {
      final h = await api.get('/health');
      setState(() => _health = 'conectado (${h['database']})');
    } catch (e) {
      setState(() => _health = 'sin conexión: $e');
    }
  }

  @override
  Widget build(BuildContext context) {
    final state = context.watch<AppState>();
    return Scaffold(
      appBar: AppBar(title: const Text('Ajustes')),
      body: ListView(children: [
        if (Install.isWeb && !Install.alreadyInstalled) ...[
          _Section('Instalar la app'),
          ListTile(
            leading: const Icon(Icons.install_mobile),
            title: const Text('Instalar Euro2 en este dispositivo'),
            subtitle: Text(Install.canPromptNatively
                ? 'Se instala desde el navegador, sin tienda, y se abre a pantalla completa.'
                : 'iPhone/iPad: Safari → Compartir → "Añadir a pantalla de inicio". '
                    'Android: menú del navegador → "Instalar aplicación".'),
            trailing: Install.canPromptNatively
                ? FilledButton(
                    onPressed: () async {
                      final r = await Install.prompt();
                      if (context.mounted && r == 'accepted') setState(() {});
                    },
                    child: const Text('Instalar'))
                : null,
          ),
        ],
        _Section('Idioma y aspecto'),
        ListTile(
          leading: const Icon(Icons.language),
          title: const Text('Idioma de los datos'),
          subtitle: const Text('Títulos, descripciones, noticias y asistente'),
          trailing: SegmentedButton<String>(
            segments: const [
              ButtonSegment(value: 'es', label: Text('ES')),
              ButtonSegment(value: 'en', label: Text('EN')),
            ],
            selected: {state.lang},
            onSelectionChanged: (s) => state.setLang(s.first),
          ),
        ),
        ListTile(
          leading: const Icon(Icons.brightness_6),
          title: const Text('Tema'),
          trailing: SegmentedButton<ThemeMode>(
            segments: const [
              ButtonSegment(value: ThemeMode.system, icon: Icon(Icons.phone_android), label: Text('Sistema')),
              ButtonSegment(value: ThemeMode.light, icon: Icon(Icons.light_mode)),
              ButtonSegment(value: ThemeMode.dark, icon: Icon(Icons.dark_mode)),
            ],
            selected: {state.themeMode},
            onSelectionChanged: (s) => state.setThemeMode(s.first),
          ),
        ),
        _Section('Servidor'),
        ListTile(
          leading: const Icon(Icons.dns),
          title: Text(state.api.baseUrl),
          subtitle: Text(_health ?? 'toca para cambiar la URL de la API'),
          onTap: _editServer,
          trailing: TextButton(onPressed: _test, child: const Text('Probar')),
        ),
        _Section('Mercado'),
        ListTile(
          leading: const Icon(Icons.storefront),
          title: const Text('Plazas para los enlaces'),
          subtitle: Wrap(spacing: 6, children: [
            for (final e in kMarketplaceLabel.entries)
              if (e.key.startsWith('EBAY_'))
                FilterChip(
                  label: Text(e.value),
                  selected: state.marketplaces.contains(e.key),
                  onSelected: (on) {
                    final next = {...state.marketplaces};
                    on ? next.add(e.key) : next.remove(e.key);
                    if (next.isNotEmpty) state.setMarketplaces(next);
                  },
                ),
          ]),
        ),
        _Section('Privacidad'),
        SwitchListTile(
          secondary: const Icon(Icons.price_check),
          title: const Text('Usar mis compras como datos de mercado'),
          subtitle: const Text(
              'Lo que pagas (sin tu nombre) mejora las valoraciones de todos. Puedes desactivarlo.'),
          value: state.sharePurchases,
          onChanged: (v) => state.setFlag('sharePurchases', v),
        ),
        _Section('Notificaciones'),
        SwitchListTile(
          secondary: const Icon(Icons.local_fire_department),
          title: const Text('Chollos en las monedas que sigo'),
          value: state.notifyDeals,
          onChanged: (v) => state.setFlag('notifyDeals', v),
        ),
        SwitchListTile(
          secondary: const Icon(Icons.trending_up),
          title: const Text('Movimientos de precio (> 20 %)'),
          value: state.notifyMoves,
          onChanged: (v) => state.setFlag('notifyMoves', v),
        ),
        _Section('Datos'),
        ListTile(
          leading: const Icon(Icons.delete_sweep),
          title: const Text('Borrar datos locales'),
          subtitle: const Text('Preferencias y sesión en este dispositivo; tu colección sigue en el servidor'),
          onTap: () async {
            final ok = await showDialog<bool>(
              context: context,
              builder: (ctx) => AlertDialog(
                title: const Text('¿Borrar datos locales?'),
                actions: [
                  TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('Cancelar')),
                  FilledButton(onPressed: () => Navigator.pop(ctx, true), child: const Text('Borrar')),
                ],
              ),
            );
            if (ok == true) await state.clearLocalData();
          },
        ),
        ListTile(
          leading: const Icon(Icons.info_outline),
          title: const Text('Acerca de Euro2'),
          subtitle: const Text('Catálogo: Banco Central Europeo (fotos © BCE, con atribución) y Numista. '
              'Valores: ventas reales, catálogo o estimación propia por tirada, siempre etiquetados. '
              'Identificación y asistente: modelos locales; nada sale de tu servidor.'),
          onTap: () => showAboutDialog(
            context: context,
            applicationName: 'Euro2',
            applicationVersion: '0.2.0',
            applicationLegalese: 'Código abierto (MIT) · github.com/Rampere-98/euro2-core',
          ),
        ),
        if (state.isAdmin) ...[
          _Section('Administración'),
          ListTile(
            leading: const Icon(Icons.admin_panel_settings),
            title: const Text('Panel del servidor'),
            subtitle: const Text('Claves de API, fuentes y sincronización, usuarios, registros, copias, actualizaciones'),
            trailing: const Icon(Icons.chevron_right),
            onTap: () => Navigator.of(context).push(MaterialPageRoute(builder: (_) => const AdminScreen())),
          ),
        ] else if (!state.loggedIn)
          const Padding(
            padding: EdgeInsets.all(16),
            child: Text('El primer usuario registrado en un servidor es su administrador.',
                style: TextStyle(fontSize: 12)),
          ),
        const SizedBox(height: 80),
      ]),
    );
  }
}

class _Section extends StatelessWidget {
  const _Section(this.title);
  final String title;

  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.fromLTRB(16, 16, 16, 4),
        child: Text(title,
            style: Theme.of(context).textTheme.labelLarge?.copyWith(color: Theme.of(context).colorScheme.primary)),
      );
}

String basisLabel(String basis) => kBasisLabel[basis] ?? basis;
