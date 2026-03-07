FROM artifacts.developer.gov.bc.ca/redhat-docker-remote/ubi9/nodejs-20:9.5-1733162459 AS builder

COPY package.json ./
RUN npm ci --only=production

FROM artifacts.developer.gov.bc.ca/redhat-docker-remote/ubi9/nodejs-20-minimal:9.5-1733162466

COPY --from=builder /opt/app-root/src/node_modules ./node_modules
COPY index.js ./

EXPOSE 8080

CMD ["node", "index.js"]
