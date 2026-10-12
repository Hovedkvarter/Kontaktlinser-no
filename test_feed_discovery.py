import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import feed_discovery as fd

class DiscoveryTests(unittest.TestCase):
    def row(self, name='Precision1 30p', **kwargs):
        return dict(sku='sku', name=name, category='Kontaktlinser > Dagslinser', description='',brand='',price='100 NOK',currency='NOK',availability='in_stock',url='https://example.com/p',image_url='',gtin='',**kwargs)

    def test_relevance_excludes_cosmetics_pets_and_false_brand_hits(self):
        for name,cat in [('Libresse Dailies','Apotek > Intim'),('Ardell Lash Glue','Skjønnhet > Kosmetikk > Øyne'),('Aptus Eye Drops','Dyrehelse')]:
            r=self.row(name);r['category']=cat
            self.assertFalse(fd.relevant(r))
        for name in ['Blephaclean','Linseetui','MediPearl','Soft Clean','Nytt produkt øyedråper','Opticlude øyelapp']:
            r=self.row(name);r['category']='Tilbehør';self.assertTrue(fd.relevant(r))

    def test_pack_variants_not_exact_match(self):
        kind,near=fd.suggestions(self.row(),[{'id':'p','name':'Precision1 90-pack'}])
        self.assertNotEqual(kind,'Mulig eksisterende produkt')
        kind,_=fd.suggestions(self.row(),[{'id':'p','name':'Precision1 30-pack'}])
        self.assertEqual(kind,'Mulig eksisterende produkt')
        _,near=fd.suggestions(self.row('Lomudal Øyedråper 20mg/ml'),[{'id':'p','name':'Artelac Øyedråper 10 ml'}])
        self.assertEqual(near,[])

    def test_fullfeed_error_is_not_empty_success(self):
        for data in [{'message':'come back'}, {'errors':[{}]}, {'products':[]}]:
            with self.assertRaises(ValueError):fd.validate_td(data)

    def test_unlimited_url_strips_search_and_pagination(self):
        u=fd.td_url({'feed_urls':['https://api.tradedoubler.com/1.0/products.json;fid=123;q=Acuvue;pageSize=100?token=fake']})
        self.assertEqual(u,'https://api.tradedoubler.com/1.0/productsUnlimited.json;fid=123?token=fake')

    def test_outage_preserves_candidates_and_never_resolves_them(self):
        config={'store':{'default_source':'affiliate_feed','network':'n','display_name':'S','feed_url':'x'}}
        old={'key':'store:sku','source':'store','name':'X','group':'Tilbehør','first_seen':'old','fingerprint':'x'}
        with patch.object(fd,'load_source',side_effect=ValueError('bad')):
            result=fd.audit(config,{},[],{'candidates':[old]}, {},Path('.'))
        self.assertFalse(result['complete']);self.assertEqual(result['resolved'],[])
        self.assertEqual(result['candidates'][0]['first_seen'],'old')

    def test_mapping_resolution_and_changed_decision(self):
        config={'store':{'default_source':'affiliate_feed','network':'n','display_name':'S'}}
        product={'id':'p','name':'Precision1 30-pack'}
        with patch.object(fd,'load_source',return_value=[self.row()]):
            first=fd.audit(config,{},[product],{}, {},Path('.'))
            item=first['candidates'][0]
            decision={item['key']:{'fingerprint':item['fingerprint'],'status':'Avklart','note':'Keep'}}
            second=fd.audit(config,{},[product],first,decision,Path('.'))
            self.assertEqual(second['candidates'][0]['review_status'],'Avklart')
            self.assertEqual(second['candidates'][0]['first_seen'],item['first_seen'])
            resolved=fd.audit(config,{'n':{'sku':'p'}},[product],first,{},Path('.'))
            self.assertEqual(len(resolved['resolved']),1);self.assertFalse(resolved['candidates'])
        changed=self.row('Precision1 90p')
        with patch.object(fd,'load_source',return_value=[changed]):
            third=fd.audit(config,{},[product],first,decision,Path('.'))
            self.assertEqual(third['candidates'][0]['review_status'],'Åpen')
            self.assertEqual(third['candidates'][0]['observation'],'Endret')

    def test_direct_urls_remove_affiliate_tokens(self):
        self.assertEqual(fd.destination('https://pdt.tradedoubler.com/click?a(1)url(https%3A%2F%2Fstore.no%2Fp%3Ftracking%3Dx)'), 'https://store.no/p')
        self.assertEqual(fd.destination('https://track.no/?url=https%3A%2F%2Fstore.no%2Fp&token=secret'), 'https://store.no/p')

    def test_collapse_guard_survives_repeated_failed_runs(self):
        config={'store':{'default_source':'affiliate_feed','network':'n','display_name':'S'}}
        previous={'sources':[{'key':'store','rows':100}], 'candidates':[]}
        with patch.object(fd,'load_source',return_value=[self.row()]):
            one=fd.audit(config,{},[],previous,{},Path('.'))
            two=fd.audit(config,{},[],one,{},Path('.'))
        self.assertFalse(one['complete']);self.assertFalse(two['complete'])
        self.assertEqual(two['sources'][0]['last_success_rows'],100)

    def test_csv_schema_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp,'store.csv').write_text('<html>error</html>')
            with self.assertRaises(ValueError):fd.load_source('store',{'feed_url':'unused'},Path(tmp),True)

if __name__=='__main__':unittest.main()
