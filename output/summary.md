# Сводка журнала запусков (30 дней, оркестратора нет)
- Всего запусков: 319; с конфликтом: 48%; упало: 33 (10%); двойных запусков (тот же процесс и дата): 5.
- Конфликт замедляет задачу в среднем в 1.17 раза.
- Самые конфликтные пары процессов: liquidity_risk + stress_test (44); credit_risk + stress_test (42); credit_risk + liquidity_risk (39).
- Самые горячие источники: limits (124); transactions (113); ratings (55).
- Час пика: 2:00, на него приходится 49% всех запусков (ночной регламент: все 5 процессов стартуют в течение 20 минут).
- Ручные запуски: конфликт у 27%, упали 4%; регламентные: конфликт у 73%, упали 17%.
- Процессы и их источники: credit_risk: crm, ratings, transactions; liquidity_risk: limits, transactions; market_risk: limits, market_data; operational_risk: crm, transactions; stress_test: limits, market_data, ratings.
