{{- range $component := list "postgres" "redis" }}
{{- $postgres := eq $component "postgres" }}
---
apiVersion: v1
kind: Service
metadata:
  name: {{ $.Release.Name }}-{{ $component }}
spec:
  clusterIP: None
  selector:
    app: {{ $.Release.Name }}-{{ $component }}
  ports:
    - port: {{ ternary 5432 6379 $postgres }}
      targetPort: database
---
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: {{ $.Release.Name }}-{{ $component }}
spec:
  serviceName: {{ $.Release.Name }}-{{ $component }}
  replicas: 1
  selector:
    matchLabels:
      app: {{ $.Release.Name }}-{{ $component }}
  template:
    metadata:
      labels:
        app: {{ $.Release.Name }}-{{ $component }}
    spec:
      automountServiceAccountToken: false
      securityContext:
        seccompProfile:
          type: RuntimeDefault
      containers:
        - name: {{ $component }}
          image: {{ (index $.Values $component).image | quote }}
          securityContext:
            allowPrivilegeEscalation: false
          ports:
            - name: database
              containerPort: {{ ternary 5432 6379 $postgres }}
          {{- if $postgres }}
          env:
            - name: POSTGRES_DB
              value: hievents
            - name: POSTGRES_USER
              value: hievents
            - name: PGDATA
              value: /var/lib/postgresql/data/pgdata
            - name: POSTGRES_PASSWORD
              valueFrom:
                secretKeyRef:
                  name: {{ $.Values.runtimeSecret }}
                  key: POSTGRES_PASSWORD
          {{- else }}
          args: ["redis-server", "--appendonly", "yes"]
          {{- end }}
          resources:
            requests:
              cpu: 100m
              memory: {{ ternary "256Mi" "128Mi" $postgres }}
            limits:
              cpu: "1"
              memory: {{ ternary "1Gi" "512Mi" $postgres }}
          readinessProbe:
            exec:
              command: {{ ternary (list "pg_isready" "-U" "hievents" "-d" "hievents") (list "redis-cli" "ping") $postgres | toJson }}
            periodSeconds: 5
          volumeMounts:
            - name: data
              mountPath: {{ ternary "/var/lib/postgresql/data" "/data" $postgres }}
  volumeClaimTemplates:
    - metadata:
        name: data
      spec:
        accessModes: [ReadWriteOnce]
        storageClassName: {{ $.Values.storage.className }}
        resources:
          requests:
            storage: {{ index $.Values.storage $component }}
{{- end }}
