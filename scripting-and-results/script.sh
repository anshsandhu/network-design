for demand_weight in 0 
do 
	for access_values in 0.1 
	do 
		python ../TLND/ansh-working-v2.py $access_values $demand_weight > demand-$demand_weight-access$access_values.txt
	done

done		

