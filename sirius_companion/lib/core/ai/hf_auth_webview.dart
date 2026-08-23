import 'dart:async';
import 'package:flutter/material.dart';
import 'package:webview_flutter/webview_flutter.dart';
import '../config/constants.dart';

class HfAuthWebView extends StatefulWidget {
  const HfAuthWebView({super.key});

  @override
  State<HfAuthWebView> createState() => _HfAuthWebViewState();
}

class _HfAuthWebViewState extends State<HfAuthWebView> {
  late final WebViewController _controller;
  bool _loading = true;
  String? _error;
  String? _currentUrl;
  String _lastCookies = '';
  bool _userConfirmed = false;
  bool _licenseAccepted = false;
  bool _autoClosing = false;
  Timer? _autoCloseTimer;

  @override
  void initState() {
    super.initState();
    _controller = WebViewController()
      ..setJavaScriptMode(JavaScriptMode.unrestricted)
      ..setNavigationDelegate(NavigationDelegate(
        onPageStarted: (url) {
          _currentUrl = url;
          if (!mounted) return;
          setState(() => _loading = true);
          debugPrint('[HF WebView] Page started: $url');
        },
        onPageFinished: (url) {
          _currentUrl = url;
          if (!mounted) return;
          setState(() => _loading = false);
          debugPrint('[HF WebView] Page finished: $url');
          _injectLicenseMonitor();
          _extractCookies();
        },
        onNavigationRequest: (request) {
          debugPrint('[HF WebView] Navigation request: ${request.url}');
          _currentUrl = request.url;
          return NavigationDecision.navigate;
        },
        onWebResourceError: (error) {
          if (!mounted) return;
          debugPrint('[HF WebView] Resource error: ${error.description} (${error.errorCode})');
        },
      ))
      ..addJavaScriptChannel(
        'HFListener',
        onMessageReceived: (message) {
          debugPrint('[HF WebView] JS Message: ${message.message}');
          if (message.message == 'LICENSE_ACCEPTED') {
            _onLicenseAcceptedFromJS();
          }
        },
      )
      ..loadRequest(Uri.parse(AppConstants.gemmaHfRepoUrl));
  }

  @override
  void dispose() {
    _autoCloseTimer?.cancel();
    super.dispose();
  }

  void _injectLicenseMonitor() {
    const script = '''
(function() {
  function checkForAgreeButton() {
    const selectors = [
      'button[data-testid="accept-license"]',
      'button:contains("Agree")',
      'button:contains("Accept")',
      'button:contains("Concordo")',
      'button:contains("Aceito")',
      '[data-target*="license"] button',
      '.license-modal button',
      'button.btn-primary',
      'button[type="submit"]',
    ];

    for (const sel of selectors) {
      try {
        const btns = document.querySelectorAll(sel);
        btns.forEach(btn => {
          if (btn.offsetParent !== null) {
            btn.addEventListener('click', () => {
              console.log('HF License button clicked');
              setTimeout(() => HFListener.postMessage('LICENSE_ACCEPTED'), 1000);
            }, { once: true });
          }
        });
      } catch (e) {}
    }

    const originalFetch = window.fetch;
    window.fetch = async function(...args) {
      const url = args[0];
      if (typeof url === 'string' && (url.includes('/license') || url.includes('/accept') || url.includes('/agree'))) {
        console.log('HF License fetch detected:', url);
        setTimeout(() => HFListener.postMessage('LICENSE_ACCEPTED'), 1500);
      }
      return originalFetch.apply(this, args);
    };

    const originalXHR = window.XMLHttpRequest.prototype.open;
    window.XMLHttpRequest.prototype.open = function(method, url) {
      if (url && (url.includes('/license') || url.includes('/accept') || url.includes('/agree'))) {
        console.log('HF License XHR detected:', url);
        this.addEventListener('load', () => {
          if (this.status === 200 || this.status === 201) {
            setTimeout(() => HFListener.postMessage('LICENSE_ACCEPTED'), 1000);
          }
        });
      }
      return originalXHR.apply(this, arguments);
    };
  }

  checkForAgreeButton();
  const observer = new MutationObserver(checkForAgreeButton);
  observer.observe(document.body, { childList: true, subtree: true });
})();
''';
    _controller.runJavaScript(script);
  }

  void _onLicenseAcceptedFromJS() {
    debugPrint('[HF WebView] License accepted detected via JS');
    setState(() => _licenseAccepted = true);
    // Wait for cookies to be set by server response
    _autoCloseTimer?.cancel();
    _autoCloseTimer = Timer(const Duration(milliseconds: 1500), () {
      if (mounted) _extractCookies();
    });
  }

  Future<void> _extractCookies() async {
    try {
      final cookiesResult = await _controller.runJavaScriptReturningResult('document.cookie');
      final cookieStr = cookiesResult.toString();
      _lastCookies = cookieStr;
      debugPrint('[HF WebView] ALL Cookies (len=${cookieStr.length}): $cookieStr');

      // Also extract HF token from localStorage
      final token = await _extractHfToken();

      // Robust session detection - HF uses various cookie names
      final hasSession = cookieStr.contains('hf-session') || 
                         cookieStr.contains('hf_chat') ||
                         cookieStr.contains('__Host-session') ||
                         cookieStr.contains('session') ||
                         cookieStr.length > 200; // Logged in = many/long cookies

      final isModelPage = _currentUrl?.contains('/google/gemma') == true || 
                          _currentUrl?.contains('/litert-community/Gemma') == true;

      debugPrint('[HF WebView] hasSession=$hasSession, isModelPage=$isModelPage, licenseAccepted=$_licenseAccepted, userConfirmed=$_userConfirmed, autoClosing=$_autoClosing, token=${token.isNotEmpty ? "***found***" : "empty"}');

      // Auto-close if: has session AND (license accepted OR user confirmed OR on model page with session)
      final shouldAutoClose = (!_autoClosing) && hasSession && (_licenseAccepted || _userConfirmed || isModelPage);

      if (shouldAutoClose) {
        _autoClosing = true;
        debugPrint('[HF WebView] Auto-closing with cookies...');
        if (!mounted) return;
        Navigator.pop(context, {
          'cookies': cookieStr,
          'token': token,
        });
      }
    } catch (e) {
      debugPrint('[HF WebView] Cookie extraction error: $e');
    }
  }

  Future<String> _extractHfToken() async {
    try {
      const script = '''
(function() {
  try {
    // Try multiple possible keys where HuggingFace stores the token
    var keys = ['token', 'hf-token', 'hf_chat_token', 'access_token', 'hf_access_token', 'userMenuToken'];
    for (var i = 0; i < keys.length; i++) {
      try {
        var val = localStorage.getItem(keys[i]);
        if (val && val.length > 5) return val;
      } catch(e) {}
    }
    // Fallback: look for a global __token variable
    try {
      if (window.__token && window.__token.length > 5) return window.__token;
    } catch(e) {}
    return '';
  } catch(e) {
    return '';
  }
})()
''';
      final result = await _controller.runJavaScriptReturningResult(script);
      final token = result.toString().trim();
      debugPrint('[HF WebView] Token extraction result (len=${token.length}): token found = ${token.isNotEmpty}');
      return token;
    } catch (e) {
      debugPrint('[HF WebView] Token extraction error: $e');
      return '';
    }
  }

  void _onUserConfirm() {
    setState(() => _userConfirmed = true);
    _extractCookies();
  }

@override
  Widget build(BuildContext context) {
    final hasCookies = _lastCookies.isNotEmpty;
    final hasSession = _lastCookies.contains('hf-session') || 
                       _lastCookies.contains('hf_chat') ||
                       _lastCookies.contains('__Host-session') ||
                       _lastCookies.length > 100;

    return PopScope(
      canPop: !(hasSession && !_autoClosing),
      onPopInvokedWithResult: (didPop, result) async {
        if (didPop) return;
        // Warn if trying to close while we have session but haven't downloaded
        if (hasSession && !_autoClosing) {
          final shouldClose = await showDialog<bool>(
            context: context,
            builder: (ctx) => AlertDialog(
              backgroundColor: const Color(0xFF0D1117),
              title: const Text('Fechar?', style: TextStyle(color: Colors.white)),
              content: const Text(
                'Você está logado e a licença foi aceita. Fechar agora pode perder o progresso do download.\n\nDeseja realmente fechar?',
                style: TextStyle(color: Color(0xFF9CA3AF)),
              ),
              actions: [
                TextButton(
                  onPressed: () => Navigator.pop(ctx, false),
                  child: const Text('Continuar', style: TextStyle(color: Color(0xFF6366F1))),
                ),
                TextButton(
                  onPressed: () => Navigator.pop(ctx, true),
                  child: const Text('Fechar mesmo assim', style: TextStyle(color: Color(0xFFEF4444))),
                ),
              ],
            ),
          );
          if (shouldClose == true && context.mounted) {
            Navigator.pop(context);
          }
        }
      },
      child: Scaffold(
        backgroundColor: const Color(0xFF07090F),
        appBar: AppBar(
          title: const Text('Login HuggingFace'),
          backgroundColor: const Color(0xFF07090F),
          leading: IconButton(
            icon: const Icon(Icons.close),
            onPressed: () => Navigator.pop(context),
          ),
          actions: [
            if (hasCookies)
              Padding(
                padding: const EdgeInsets.only(right: 8),
                child: Chip(
                  label: Text(
                    hasSession ? 'Logado ✓' : 'Sem sessão',
                    style: const TextStyle(fontSize: 11, color: Colors.white),
                  ),
                  backgroundColor: hasSession ? const Color(0xFF22C55E) : const Color(0xFFF59E0B),
                  padding: EdgeInsets.zero,
                  visualDensity: VisualDensity.compact,
                ),
              ),
          ],
        ),
        body: Stack(
          children: [
            WebViewWidget(controller: _controller),
            if (_loading && !_autoClosing)
              const Center(
                child: CircularProgressIndicator(color: Color(0xFF6366F1)),
              ),
            if (_error != null)
              Center(
                child: Padding(
                  padding: const EdgeInsets.all(24),
                  child: Column(
                    mainAxisAlignment: MainAxisAlignment.center,
                    children: [
                      const Icon(Icons.error_outline, color: Color(0xFFEF4444), size: 48),
                      const SizedBox(height: 16),
                      Text(
                        _error!,
                        style: const TextStyle(color: Color(0xFFEF4444), fontSize: 14),
                        textAlign: TextAlign.center,
                      ),
                      const SizedBox(height: 16),
                      FilledButton(
                        onPressed: () {
                          setState(() => _error = null);
                          _controller.reload();
                        },
                        child: const Text('Tentar novamente'),
                      ),
                    ],
                  ),
                ),
              ),
            if (_autoClosing)
              const Center(
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    CircularProgressIndicator(color: Color(0xFF6366F1)),
                    SizedBox(height: 16),
                    Text('Finalizando...', style: TextStyle(color: Colors.white, fontSize: 16)),
                  ],
                ),
              ),
            Positioned(
              bottom: 16,
              left: 16,
              right: 16,
              child: Column(
                mainAxisSize: MainAxisSize.min,
                children: [
                  Container(
                    padding: const EdgeInsets.all(12),
                    decoration: BoxDecoration(
                      color: const Color(0xFF1F2937),
                      borderRadius: BorderRadius.circular(12),
                    ),
                    child: Column(
                      children: [
                        Text(
                          _getInstructions(),
                          style: const TextStyle(color: Color(0xFF9CA3AF), fontSize: 12),
                          textAlign: TextAlign.center,
                        ),
                        const SizedBox(height: 8),
                        Text(
                          'URL: ${_currentUrl?.replaceAll('https://huggingface.co/', 'hf.co/') ?? 'carregando...'}',
                          style: const TextStyle(color: Color(0xFF6B7280), fontSize: 10, fontFamily: 'monospace'),
                          textAlign: TextAlign.center,
                          maxLines: 2,
                          overflow: TextOverflow.ellipsis,
                        ),
                        if (_licenseAccepted) ...[
                          const SizedBox(height: 8),
                          const Text(
                            '✅ Licença detectada como aceita!',
                            style: TextStyle(color: Color(0xFF22C55E), fontSize: 11, fontWeight: FontWeight.w600),
                          ),
                        ],
                        if (_autoClosing) ...[
                          const SizedBox(height: 8),
                          const Text(
                            '⏳ Finalizando e voltando ao app...',
                            style: TextStyle(color: Color(0xFF6366F1), fontSize: 11, fontWeight: FontWeight.w600),
                          ),
                        ],
                      ],
                    ),
                  ),
                  const SizedBox(height: 12),
                  if (hasSession && (_licenseAccepted || _isOnModelPage()))
                    SizedBox(
                      width: double.infinity,
                      child: FilledButton.icon(
                        icon: const Icon(Icons.check_circle, size: 18),
                        label: const Text('Continuar para download'),
                        style: FilledButton.styleFrom(
                          backgroundColor: const Color(0xFF6366F1),
                          padding: const EdgeInsets.symmetric(vertical: 14),
                          shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
                        ),
                        onPressed: _onUserConfirm,
                      ),
                    )
                  else if (hasSession)
                    SizedBox(
                      width: double.infinity,
                      child: FilledButton.icon(
                        icon: const Icon(Icons.check_circle, size: 18),
                        label: const Text('Já aceitei a licença — Continuar'),
                        style: FilledButton.styleFrom(
                          backgroundColor: const Color(0xFF6366F1),
                          padding: const EdgeInsets.symmetric(vertical: 14),
                          shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
                        ),
                        onPressed: _onUserConfirm,
                      ),
                    )
                  else
                    OutlinedButton.icon(
                      icon: const Icon(Icons.refresh, size: 18),
                      label: const Text('Recarregar página'),
                      style: OutlinedButton.styleFrom(
                        foregroundColor: const Color(0xFF9CA3AF),
                        side: const BorderSide(color: Color(0xFF374151)),
                        padding: const EdgeInsets.symmetric(vertical: 14),
                        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
                      ),
                      onPressed: () => _controller.reload(),
                    ),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }

  bool _isOnModelPage() {
    return _currentUrl?.contains('/google/gemma') == true || 
           _currentUrl?.contains('/litert-community/Gemma') == true;
  }

  String _getInstructions() {
    if (_lastCookies.isEmpty) {
      return 'Aguarde o carregamento...';
    }
    if (hasSession) {
      if (_licenseAccepted || _isOnModelPage()) {
        return '✅ Login detectado. Licença aceita ou na página do modelo. Toque em "Continuar para download".';
      }
      return '✅ Login detectado. Navegue até a página do modelo e clique em "Agree/Accept" para aceitar a licença, depois toque no botão abaixo.';
    }
    return '🔐 Faça login no HuggingFace. Após logar, vá para a página do modelo e aceite a licença clicando em "Agree".';
  }

  bool get hasSession => _lastCookies.contains('hf-session') || 
                         _lastCookies.contains('hf_chat') ||
                         _lastCookies.contains('__Host-session') ||
                         _lastCookies.length > 200;
}