<?php

namespace Laravel\Nova\Fields;

use Brick\Money\Context\CustomContext;
use Brick\Money\Money;
use Symfony\Component\Intl\Currencies;

class Currency extends Number
{
    /**
     * The field's component.
     *
     * @var string
     */
    public $component = 'currency-field';

    /**
     * The format the field will be displayed in.
     *
     * @var string
     */
    public $format;

    /**
     * The locale of the field.
     *
     * @var string
     */
    public $locale;

    /**
     * The currency of the value.
     *
     * @var string
     */
    public $currency;

    /**
     * The symbol used by the currency.
     *
     * @var null|string
     */
    public $currencySymbol = null;

    /**
     * Whether the currency is using minor units.
     *
     * @var bool
     */
    public $minorUnits = false;

    /**
     * Create a new field.
     *
     * @param  string  $name
     * @param  string|null  $attribute
     * @param  mixed|null  $resolveCallback
     * @return void
     */
    public function __construct($name, $attribute = null, $resolveCallback = null)
    {
        parent::__construct($name, $attribute, $resolveCallback);

        $this->locale = config('app.locale', 'en');
        $this->currency = config('nova.currency', 'USD');

        $this->step($this->getStepValue());

        $this->fillUsing(function ($request, $model, $attribute) {
            $value = $request->$attribute;

            if ($this->minorUnits) {
                $model->$attribute = $this->toMoneyInstance($value)->getMinorAmount()->toInt();
            } else {
                $model->$attribute = $value;
            }
        })
            ->displayUsing(function ($value) {
                return ! $this->isNullValue($value) ? $this->formatMoney($value) : null;
            })
            ->resolveUsing(function ($value) {
                if (! $this->minorUnits) {
                    return $value;
                }

                return $this->toMoneyInstance($value)->getMinorAmount()->toInt();
            });
    }

    /**
     * Convert the value to a Money instance.
     *
     * @param mixed $value
     * @param null|string $currency
     *
     * @return \Brick\Money\Money
     */
    public function toMoneyInstance($value, $currency = null)
    {
        $currency = $currency ?? $this->currency;
        $method = $this->minorUnits ? 'ofMinor' : 'of';

        $context = new CustomContext(Currencies::getFractionDigits($currency));

        return Money::{$method}($value, $currency, $context);
    }

    /**
     * Format the field's value into Money format.
     *
     * @param  mixed  $value
     * @param  null|string  $currency
     * @param  null|string  $locale
     *
     * @return string
     */
    public function formatMoney($value, $currency = null, $locale = null)
    {
        $money = $this->toMoneyInstance($value, $currency);

        return $money->formatTo($locale ?? $this->locale);
    }

    /**
     * Set the currency code for the field.
     *
     * @param  string  $currency
     * @return $this
     */
    public function currency($currency)
    {
        $this->currency = strtoupper($currency);

        $this->step($this->getStepValue());

        return $this;
    }

    /**
     * Set the field locale.
     *
     * @param  string  $locale
     * @return $this
     */
    public function locale($locale)
    {
        $this->locale = $locale;

        return $this;
    }

    /**
     * Set the symbol used by the field.
     *
     * @param  string  $symbol
     * @return $this
     */
    public function symbol($symbol)
    {
        $this->currencySymbol = $symbol;

        return $this;
    }

    /**
     * Instruct the field to use minor units.
     *
     * @return $this
     */
    public function asMinorUnits()
    {
        $this->minorUnits = true;
        $this->step('1.0');

        return $this;
    }

    /**
     * Instruct the field to use major units.
     *
     * @return $this
     */
    public function asMajorUnits()
    {
        $this->minorUnits = false;
        $this->step($this->getStepValue());

        return $this;
    }

    /**
     * Resolve the symbol used by the currency.
     *
     * @return string
     */
    public function resolveCurrencySymbol()
    {
        if ($this->currencySymbol) {
            return $this->currencySymbol;
        }

        return Currencies::getSymbol($this->currency);
    }

    /**
     * Determine the step value for the field.
     *
     * @return string
     */
    protected function getStepValue()
    {
        if ($this->minorUnits) {
            return '1.0';
        }

        return (string) 0.1 ** Currencies::getFractionDigits($this->currency);
    }

    /**
     * Prepare the field for JSON serialization.
     *
     * @return array
     */
    public function jsonSerialize()
    {
        return array_merge(parent::jsonSerialize(), [
            'currency' => $this->resolveCurrencySymbol(),
            'currency_name' => Currencies::getName($this->currency),
        ]);
    }
}
