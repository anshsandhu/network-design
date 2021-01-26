for demand_weight in 0
do 
	for access_values in 0.1 0.2 0.3 0.4 0.5 0.6 0.7 0.8 0.9 0.99 1.0
	do 
		python ../TLND/baseline.py $access_values $demand_weight > demand-$demand_weight-access$access_values.txt
	done

done		

