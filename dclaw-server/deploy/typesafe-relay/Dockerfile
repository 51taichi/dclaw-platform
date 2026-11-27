FROM node:22-alpine

WORKDIR /app

COPY --chown=node:node package.json ./
COPY --chown=node:node src ./src

ENV HOST=0.0.0.0
ENV PORT=8787

USER node

EXPOSE 8787

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD node -e "fetch('http://127.0.0.1:8787/v1/systemone').then(r=>process.exit(r.status===405?0:1)).catch(()=>process.exit(1))"

CMD ["node", "src/server.js"]
