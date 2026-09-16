{{- $digest := required "image.digest is required" .Values.image.digest -}}
{{- if not (regexMatch "^sha256:[a-f0-9]{64}$" $digest) -}}
{{- fail "image.digest must be an immutable sha256 digest" -}}
{{- end }}
apiVersion: apps/v1
kind: Deployment
metadata:
  name: {{ .Release.Name }}
spec:
  replicas: 1
  strategy:
    type: Recreate
  selector:
    matchLabels:
      app: {{ .Release.Name }}
  template:
    metadata:
      labels:
        app: {{ .Release.Name }}
    spec:
      automountServiceAccountToken: false
      securityContext:
        seccompProfile:
          type: RuntimeDefault
      imagePullSecrets:
        {{- toYaml .Values.imagePullSecrets | nindent 8 }}
      terminationGracePeriodSeconds: 90
      containers:
        - name: app
          image: "{{ .Values.image.repository }}@{{ $digest }}"
          securityContext:
            allowPrivilegeEscalation: false
          ports:
            - name: http
              containerPort: 80
          envFrom:
            - configMapRef:
                name: {{ .Release.Name }}
            - secretRef:
                name: {{ .Values.runtimeSecret }}
          resources:
            {{- toYaml .Values.resources | nindent 12 }}
          startupProbe:
            httpGet:
              path: /auth/login
              port: http
            periodSeconds: 10
            failureThreshold: 90
          readinessProbe:
            httpGet:
              path: /auth/login
              port: http
            periodSeconds: 10
          livenessProbe:
            tcpSocket:
              port: http
            periodSeconds: 30
          volumeMounts:
            - name: uploads
              mountPath: /app/backend/storage/app
      volumes:
        - name: uploads
          persistentVolumeClaim:
            claimName: {{ .Release.Name }}-uploads
---
apiVersion: v1
kind: Service
metadata:
  name: {{ .Release.Name }}
spec:
  selector:
    app: {{ .Release.Name }}
  ports:
    - name: http
      port: 80
      targetPort: http
---
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: {{ .Release.Name }}-uploads
  annotations:
    helm.sh/resource-policy: keep
spec:
  accessModes: [ReadWriteOnce]
  storageClassName: {{ .Values.storage.className }}
  resources:
    requests:
      storage: {{ .Values.storage.uploads }}
