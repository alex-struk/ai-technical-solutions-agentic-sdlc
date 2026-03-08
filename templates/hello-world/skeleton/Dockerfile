FROM registry.access.redhat.com/ubi9/nodejs-20:1-1734584268 AS builder

COPY package.json ./
RUN npm ci --only=production

FROM registry.access.redhat.com/ubi9/nodejs-20-minimal:1-63

COPY --from=builder /opt/app-root/src/node_modules ./node_modules
COPY index.js ./

EXPOSE 8080

CMD ["node", "index.js"]
