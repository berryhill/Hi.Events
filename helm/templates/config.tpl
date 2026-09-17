apiVersion: v1
kind: ConfigMap
metadata:
  name: {{ .Release.Name }}
data:
  APP_ENV: production
  APP_DEBUG: "false"
  APP_URL: "https://{{ .Values.host }}"
  APP_FRONTEND_URL: "https://{{ .Values.host }}"
  APP_CDN_URL: "https://{{ .Values.host }}/storage"
  VITE_FRONTEND_URL: "https://{{ .Values.host }}"
  VITE_API_URL_CLIENT: "https://{{ .Values.host }}/api"
  VITE_API_URL_SERVER: "http://localhost/api"
  VITE_APP_NAME: Hi.Events
  VITE_STRIPE_PUBLISHABLE_KEY: ""
  APP_DISABLE_REGISTRATION: {{ .Values.registrationDisabled | quote }}
  APP_SAAS_MODE_ENABLED: "false"
  LOG_CHANNEL: stderr
  QUEUE_CONNECTION: redis
  WEBHOOK_QUEUE_NAME: webhook-queue
  REDIS_HOST: "{{ .Release.Name }}-redis"
  REDIS_PORT: "6379"
  FILESYSTEM_PUBLIC_DISK: public
  FILESYSTEM_PRIVATE_DISK: local
  MAIL_MAILER: smtp
  MAIL_HOST: {{ .Values.mail.host | quote }}
  MAIL_PORT: {{ .Values.mail.port | quote }}
  MAIL_ENCRYPTION: {{ .Values.mail.encryption | quote }}
  MAIL_AUTO_TLS: "true"
  MAIL_VERIFY_PEER: "true"
  MAIL_FROM_ADDRESS: {{ .Values.mail.fromAddress | quote }}
  MAIL_FROM_NAME: {{ .Values.mail.fromName | quote }}
---
{{- if .Values.ingress.enabled }}
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: {{ .Release.Name }}
  annotations:
    cert-manager.io/cluster-issuer: {{ .Values.ingress.issuer | quote }}
    nginx.ingress.kubernetes.io/proxy-body-size: "20m"
    nginx.ingress.kubernetes.io/ssl-redirect: "true"
spec:
  ingressClassName: {{ .Values.ingress.className }}
  tls:
    - hosts:
        - {{ .Values.host | quote }}
      secretName: {{ .Release.Name }}-tls
  rules:
    - host: {{ .Values.host | quote }}
      http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service:
                name: {{ .Release.Name }}
                port:
                  number: 80
{{- end }}
