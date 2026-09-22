import httpx

headers = {
    'X-N8N-API-KEY': 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiI1YjYxMWZkZC00NWVmLTRhMTMtYTQ5OS0xOGQ1MmVjMzg2ZmYiLCJpc3MiOiJuOG4iLCJhdWQiOiJwdWJsaWMtYXBpIiwianRpIjoiNjg5MzgxMjctNGQ5Yy00MTYzLWI1MWEtYjBlMzk1YjRiNWM5IiwiaWF0IjoxNzkwMTAzNzY2LCJleHAiOjE3OTI2MzgwMDB9.Yst7jcezSKCZb4aHGf8bj_QfYIBqRL88SL0JaAOKts8'
}

workflow = {
    'name': 'Catalogo 3D - Notificacao WhatsApp',
    'nodes': [
        {
            'parameters': {
                'httpMethod': 'POST',
                'path': 'catalogo-pedido',
                'responseMode': 'responseNode',
                'options': {}
            },
            'id': 'e6741b0b-c8c3-4d6d-88b1-9f2cb42b8e30',
            'name': 'Webhook Pedido',
            'type': 'n8n-nodes-base.webhook',
            'typeVersion': 2,
            'position': [240, 300],
            'webhookId': 'catalogo-pedido'
        },
        {
            'parameters': {
                'method': 'POST',
                'url': 'https://evowsapi.3afieldservice.com.br/message/sendMedia/default',
                'sendHeaders': True,
                'headerParameters': {
                    'parameters': [
                        {
                            'name': 'apikey',
                            'value': '4eddc4b3-5499-47a1-9b8b-d4afa9ad00e8'
                        },
                        {
                            'name': 'Content-Type',
                            'value': 'application/json'
                        }
                    ]
                },
                'sendBody': True,
                'specifyBody': 'json',
                'jsonBody': '={\n  "number": "{{ $json.body.whatsapp_dest }}",\n  "mediatype": "image",\n  "mimetype": "image/jpeg",\n  "caption": "{{ $json.body.message }}",\n  "media": "{{ $json.body.image_url }}",\n  "fileName": "{{ $json.body.model.title }}.jpg"\n}',
                'options': {}
            },
            'id': '11904a43-0c4a-4ff1-b847-8149d5bf1c42',
            'name': 'Evolution API - Enviar WhatsApp',
            'type': 'n8n-nodes-base.httpRequest',
            'typeVersion': 4.2,
            'position': [480, 300]
        },
        {
            'parameters': {
                'respondWith': 'json',
                'responseBody': '={\n  "ok": true,\n  "message": "Notificacao enviada com sucesso ao WhatsApp"\n}',
                'options': {}
            },
            'id': 'acfa8122-3837-4f67-a066-b25055018693',
            'name': 'Responder Webhook',
            'type': 'n8n-nodes-base.respondToWebhook',
            'typeVersion': 1.1,
            'position': [720, 300]
        }
    ],
    'connections': {
        'Webhook Pedido': {
            'main': [
                [
                    {
                        'node': 'Evolution API - Enviar WhatsApp',
                        'type': 'main',
                        'index': 0
                    }
                ]
            ]
        },
        'Evolution API - Enviar WhatsApp': {
            'main': [
                [
                    {
                        'node': 'Responder Webhook',
                        'type': 'main',
                        'index': 0
                    }
                ]
            ]
        }
    },
    'settings': {
        'executionOrder': 'v1'
    }
}

r = httpx.post('https://editoncst.3afieldservice.com.br/api/v1/workflows', headers=headers, json=workflow, timeout=10)
print('STATUS:', r.status_code)
wf_created = r.json()
print('ID:', wf_created.get('id'), 'NAME:', wf_created.get('name'))

wf_id = wf_created.get('id')
if wf_id:
    r_act = httpx.post(f'https://editoncst.3afieldservice.com.br/api/v1/workflows/{wf_id}/activate', headers=headers, timeout=10)
    print('ACTIVATE STATUS:', r_act.status_code)
