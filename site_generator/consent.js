/* Consent v2. No network calls; GTM remains gated by reviewed configuration.
 * Acquisition cookie is read only by the existing /go/ edge, never a provider.
 * Browser metadata is evidence supplied by the browser, not Ads verification.
 */
(function () {
  'use strict';
  var cfg = window.__klTrackingConfig || {};
  var KEY = 'kl_consent_v2', CONTEXT = 'kl_acquisition_v1';
  var current = {stats:false, affiliate:false, ads:false};
  var overlay = document.getElementById('consent-overlay');
  window.dataLayer = window.dataLayer || [];
  function command() { window.dataLayer.push(arguments); }
  function signals(c) {
    return {analytics_storage:c.stats ? 'granted':'denied',
      ad_storage:c.ads ? 'granted':'denied', ad_user_data:c.ads ? 'granted':'denied',
      ad_personalization:'denied'};
  }
  command('consent', 'default', signals(current));
  // Migration never infers new advertising permission from the old banner.
  function read() {
    try {
      var c = JSON.parse(localStorage.getItem(KEY));
      if (c && c.version === 2 && ['stats','affiliate','ads'].every(function(k) {
        return typeof c[k] === 'boolean';
      }) && Number.isFinite(c.at) && Date.now() - c.at >= 0 &&
          Date.now() - c.at < 180 * 86400000) return c;
    } catch (_) {}
    return null;
  }
  function clearContext() {
    try { sessionStorage.removeItem(CONTEXT); } catch (_) {}
    document.cookie = CONTEXT + '=; Path=/go/; Max-Age=0; Secure; SameSite=Lax';
  }
  function capture(refreshOnly) {
    if (cfg.acquisition_enabled !== true || !current.ads || !current.affiliate) {
      clearContext(); return;
    }
    var ttl = cfg.context_ttl_seconds;
    if (!Number.isInteger(ttl) || ttl < 60 || ttl > 1800 || !/^\d{1,20}$/.test(cfg.account_id)) {
      clearContext(); return;
    }
    var q = new URL(window.location.href).searchParams;
    var ids = ['gclid','gbraid','wbraid'].filter(function(k) { return q.has(k); });
    var c = null;
    // New paid landing replaces the prior visit; invalid/new denied context
    // must not inherit another campaign. Never capture before permission.
    if (!refreshOnly && (ids.length || q.has('kl_campaign'))) {
      clearContext();
      var campaign = q.get('kl_campaign');
      if (ids.length !== 1 || q.getAll(ids[0]).length !== 1 ||
          q.getAll('kl_campaign').length !== 1 || !/^\d{1,20}$/.test(campaign || '') ||
          !/^[A-Za-z0-9_-]{1,256}$/.test(q.get(ids[0]) || '')) return;
      c = {version:1, visit_id:crypto.randomUUID(), account_id:cfg.account_id,
        campaign_id:campaign, ad_id_kind:ids[0], ad_id:q.get(ids[0]),
        acquired_at:Math.floor(Date.now()/1000), ads:true, affiliate:true};
      try { sessionStorage.setItem(CONTEXT, JSON.stringify(c)); } catch (_) {}
    } else {
      try { c = JSON.parse(sessionStorage.getItem(CONTEXT)); } catch (_) {}
    }
    var remaining = c && ttl - (Math.floor(Date.now()/1000) - c.acquired_at);
    if (!c || c.account_id !== cfg.account_id || remaining <= 0 || remaining > ttl) {
      clearContext(); return;
    }
    document.cookie = CONTEXT + '=' + encodeURIComponent(JSON.stringify(c)) +
      '; Path=/go/; Max-Age=' + Math.floor(remaining) + '; Secure; SameSite=Lax';
    return c;
  }
  function apply(c) {
    current = c;
    window.__klConsent = c;
    // GA4 kill switch also acts when GTM is already loaded after withdrawal.
    window['ga-disable-G-ELJYYBLS6H'] = !c.stats;
    command('consent', 'update', signals(c));
    capture();
    // The live container has an unrelated Custom HTML tag. Consent Mode does
    // not control arbitrary scripts: activation requires a reviewed container.
    if (cfg.gtm_consent_reviewed === true && (c.stats || c.ads) && window.__loadGTM) window.__loadGTM();
  }
  function save(c) {
    c.version = 2; c.at = Date.now();
    try { localStorage.setItem(KEY, JSON.stringify(c)); } catch (_) {}
    apply(c);
  }
  window.__klTrack = function(event) {
    if (current.stats && cfg.gtm_consent_reviewed === true) window.dataLayer.push(event);
  };
  function settings() {
    if (!overlay) return;
    ['stats','affiliate','ads'].forEach(function(k) {
      document.getElementById('consent-' + k).checked = current[k];
    });
    overlay.hidden = false;
    document.getElementById('consent-step-main').hidden = true;
    document.getElementById('consent-step-settings').hidden = false;
    document.getElementById('consent-stats').focus();
  }
  window.__klOpenConsent = settings;
  var saved = read();
  apply(saved || current);
  if (!saved && overlay) overlay.hidden = false;
  function on(id, fn) { var el=document.getElementById(id); if(el) el.addEventListener('click',fn); }
  on('consent-accept', function() { save({stats:true,affiliate:true,ads:true}); overlay.hidden=true; });
  on('consent-reject', function() { save({stats:false,affiliate:false,ads:false}); overlay.hidden=true; });
  on('consent-customize', settings);
  on('consent-back', function() {
    document.getElementById('consent-step-settings').hidden=true;
    document.getElementById('consent-step-main').hidden=false;
  });
  on('consent-save', function() {
    var c={}; ['stats','affiliate','ads'].forEach(function(k) { c[k]=document.getElementById('consent-'+k).checked; });
    save(c); overlay.hidden=true;
  });
  on('consent-toggle-providers', function() {
    var el=document.getElementById('consent-providers-list'); el.hidden=!el.hidden;
  });
  // Withdrawal in another tab takes effect before its next click as well.
  window.addEventListener('storage', function(e) { if (e.key===KEY || e.key===null) apply(read() || {stats:false,affiliate:false,ads:false}); });
  // Keep the supplied network URL intact. Never invent an untracked URL for
  // an unverified network. Denied affiliate actions open the existing choices.
  function affiliateGuard(e) {
    var a=e.target.closest('a[data-affiliate="1"]');
    if (a && !current.affiliate) { e.preventDefault(); settings(); }
    if (a && current.affiliate && cfg.acquisition_enabled === true &&
        (cfg.pilot_paths || []).includes(new URL(window.location.href).pathname) &&
        (cfg.pilot_retailers || []).includes(a.getAttribute('data-retailer'))) {
      var destination=new URL(a.href, window.location.href);
      if (destination.origin === new URL(window.location.href).origin &&
          /^\/go\/tgt_[A-Z0-9]{26}$/.test(destination.pathname)) {
        destination.searchParams.delete('acq_visit');
        var c=capture(true);
        if (c) destination.searchParams.set('acq_visit',c.visit_id);
        a.href=destination.href;
      }
    }
  }
  ['click','auxclick','contextmenu'].forEach(function(name) {
    document.addEventListener(name, affiliateGuard, true);
  });
  document.addEventListener('click', function(e) {
    if (e.target.closest('[data-consent-open]')) { e.preventDefault(); settings(); return; }
    var link=e.target.closest('a[data-retailer]');
    if (!link || e.defaultPrevented || e.button!==0) return;
    window.__klTrack({event:'outbound_click',retailer:link.getAttribute('data-retailer'),
      affiliate:link.getAttribute('data-affiliate')==='1'});
  });
})();
